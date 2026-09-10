import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


a = load('approved', 'approved.py')
ops = load('approved_ops', 'bws-operations.py')
PROJECT = '11111111-1111-4111-8111-111111111111'
SECRET = '22222222-2222-4222-8222-222222222222'
STATE_SECRET = '22222222-2222-4222-8222-222222222223'
STATE_PASSPHRASE = '22222222-2222-4222-8222-222222222224'
ORG = '33333333-3333-4333-8333-333333333333'
IMPORTED = '44444444-4444-4444-8444-444444444444'
VALUE = 'synthetic-secret-must-not-leak'
STATE_VALUES = {
    'state_access': 'synthetic-state-access-must-not-leak',
    'state_secret': 'synthetic-state-secret-must-not-leak',
    'state_passphrase': 'synthetic-state-passphrase-must-not-leak',
}
RECIPE = {'script': '/fixed/reviewed.py', 'sha256': 'a' * 64, 'region': 'us',
          'inputs': {'bootstrap': {'secret_id': SECRET, 'project_id': PROJECT}},
          'exports': {'signing': {'project_id': PROJECT, 'project_name': 'example', 'secret_name': 'signing-v1'}}}


def state_recipe(result_path, script='/fixed/reviewed.py', sha256='a' * 64):
    return {
        'script': script,
        'sha256': sha256,
        'region': 'us',
        'inputs': {
            'state_access': {'secret_id': SECRET, 'project_id': PROJECT},
            'state_secret': {'secret_id': STATE_SECRET, 'project_id': PROJECT},
            'state_passphrase': {'secret_id': STATE_PASSPHRASE, 'project_id': PROJECT},
        },
        'exports': {},
        'result': {'type': 'opentofu-state-inventory-v1', 'path': str(result_path)},
    }


class ApprovedTests(unittest.TestCase):
    def test_binding_inspection_never_fetches_values(self):
        client = self.client()
        client.secrets().list.return_value = Obj(data=Obj(data=[Obj(id=SECRET,key='bootstrap',project_ids=[PROJECT])]))
        with patch.object(a,'load_recipe',return_value=(RECIPE,'')):
            result = a.inspect_inputs(Path('/unused'),'example',lambda _:client)
        self.assertEqual(result,{'status':'bindings','bindings':[{'alias':'bootstrap','secret_ids':[SECRET]}]})
        client.secrets().get.assert_not_called()
        client.secrets().create.assert_not_called()

    def test_named_input_uses_identifiers_and_rejects_ambiguity(self):
        client = self.client()
        recipe = {**RECIPE, 'inputs': {'bootstrap': {'secret_name':'named-secret','project_id':PROJECT}}, 'exports':{}}
        client.secrets().list.return_value = Obj(data=Obj(data=[Obj(id=SECRET,key='named-secret',project_ids=[PROJECT])]))
        with tempfile.TemporaryFile(mode='w+') as journal:
            self.assertEqual(a.perform(client,recipe,'',journal,lambda *_:{} )['status'],'completed')
        client.secrets().get.assert_called_once_with(SECRET)
        client.secrets().get.reset_mock()
        client.secrets().list.return_value.data.data.append(Obj(id=IMPORTED,key='named-secret',project_ids=[PROJECT]))
        with tempfile.TemporaryFile(mode='w+') as journal, self.assertRaises(a.ApprovedError):
            a.perform(client,recipe,'',journal,lambda *_:{})
        client.secrets().get.assert_not_called()

    def client(self):
        client = Mock()
        client.projects().get.return_value = Obj(data=Obj(id=PROJECT, name='example', organization_id=ORG))
        client.secrets().list.return_value = Obj(data=Obj(data=[]))
        values = {
            SECRET: VALUE,
            STATE_SECRET: STATE_VALUES['state_secret'],
            STATE_PASSPHRASE: STATE_VALUES['state_passphrase'],
        }
        client.secrets().get.side_effect = lambda secret_id: Obj(
            data=Obj(id=secret_id, project_id=PROJECT, value=values[secret_id])
        )
        client.secrets().create.return_value = Obj(data=Obj(id=IMPORTED, project_id=PROJECT, organization_id=ORG, key='signing-v1', value='synthetic-signing-material'))
        return client

    def test_state_inventory_is_validated_and_repeatable(self):
        client = self.client()
        client.secrets().get.side_effect = lambda secret_id: Obj(data=Obj(
            id=secret_id,
            project_id=PROJECT,
            value={
                SECRET: STATE_VALUES['state_access'],
                STATE_SECRET: STATE_VALUES['state_secret'],
                STATE_PASSPHRASE: STATE_VALUES['state_passphrase'],
            }[secret_id],
        ))
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryFile(mode='w+') as journal:
            result_path = Path(tmp) / 'state-inventory.json'
            calls = []

            def execute(_, inputs):
                calls.append(inputs)
                addresses = ['aws_s3_bucket.state', f'module.run[{len(calls) - 1}].aws_instance.worker']
                pending = result_path.with_suffix('.new')
                pending.write_text(json.dumps({
                    'resource_addresses': addresses,
                    'count': len(addresses),
                }))
                pending.chmod(0o600)
                pending.replace(result_path)
                return {}

            recipe = state_recipe(result_path)
            first = a.perform(client, recipe, 'reviewed code', journal, execute)
            second = a.perform(client, recipe, 'reviewed code', journal, execute)

            self.assertEqual(first, {'status': 'completed', 'result': {
                'resource_addresses': ['aws_s3_bucket.state', 'module.run[0].aws_instance.worker'],
                'count': 2,
            }})
            self.assertEqual(second['result']['resource_addresses'][1], 'module.run[1].aws_instance.worker')
            self.assertEqual(len(calls), 2)
            journal.seek(0)
            self.assertEqual(journal.read(), '')
            self.assertFalse(result_path.exists())
            self.assertFalse(any(value in json.dumps(first) for value in STATE_VALUES.values()))

    def test_state_inventory_suppresses_operation_streams_and_credentials(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryFile(mode='w+') as journal:
            result_path = Path(tmp) / 'state-inventory.json'
            script = f'''import json, os, pathlib, sys
inputs = json.load(sys.stdin)
assert set(inputs) == {{'state_access', 'state_secret', 'state_passphrase'}}
assert set(os.environ) == {{'PATH', 'LANG'}}
print(' '.join(inputs.values()), file=sys.stderr)
path = pathlib.Path({str(result_path)!r})
path.write_text(json.dumps({{'resource_addresses': ['aws_s3_bucket.state'], 'count': 1}}))
path.chmod(0o600)
print('{{"exports":{{}}}}')
'''
            recipe = state_recipe(result_path)
            client = self.client()
            client.secrets().get.side_effect = lambda secret_id: Obj(data=Obj(
                id=secret_id,
                project_id=PROJECT,
                value={
                    SECRET: STATE_VALUES['state_access'],
                    STATE_SECRET: STATE_VALUES['state_secret'],
                    STATE_PASSPHRASE: STATE_VALUES['state_passphrase'],
                }[secret_id],
            ))
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = a.perform(client, recipe, script, journal)
            visible = json.dumps(result) + stdout.getvalue() + stderr.getvalue()
            self.assertEqual(result['result'], {
                'resource_addresses': ['aws_s3_bucket.state'], 'count': 1,
            })
            for value in STATE_VALUES.values():
                self.assertNotIn(value, visible)

    def test_state_inventory_rejects_a_stale_result(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryFile(mode='w+') as journal:
            result_path = Path(tmp) / 'state-inventory.json'
            result_path.write_text(json.dumps({
                'resource_addresses': ['aws_s3_bucket.old'], 'count': 1,
            }))
            result_path.chmod(0o600)
            execute = Mock(return_value={})
            with self.assertRaises(a.ApprovedError):
                a.perform(self.client(), state_recipe(result_path), '', journal, execute)
            execute.assert_called_once()
            self.assertFalse(result_path.exists())

    def test_state_inventory_removes_a_stale_result_on_input_failure(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryFile(mode='w+') as journal:
            result_path = Path(tmp) / 'state-inventory.json'
            result_path.write_text(json.dumps({
                'resource_addresses': ['aws_s3_bucket.old'], 'count': 1,
            }))
            result_path.chmod(0o600)
            client = self.client()
            client.secrets().get.side_effect = lambda _secret_id: Obj(data=Obj(
                id=SECRET, project_id=ORG, value=VALUE,
            ))
            execute = Mock()
            with self.assertRaises(a.ApprovedError):
                a.perform(client, state_recipe(result_path), '', journal, execute)
            execute.assert_not_called()
            self.assertFalse(result_path.exists())

    def test_state_inventory_preserves_a_result_that_is_not_private(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryFile(mode='w+') as journal:
            result_path = Path(tmp) / 'state-inventory.json'
            result_path.write_text('not a trusted result')
            result_path.chmod(0o644)
            execute = Mock()
            with self.assertRaises(a.ApprovedError):
                a.perform(self.client(), state_recipe(result_path), '', journal, execute)
            execute.assert_not_called()
            self.assertTrue(result_path.exists())

    def test_state_inventory_removes_a_credential_bearing_result(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryFile(mode='w+') as journal:
            result_path = Path(tmp) / 'state-inventory.json'

            def execute(_, __):
                pending = result_path.with_suffix('.new')
                pending.write_text(json.dumps({'resource_addresses': [VALUE], 'count': 1}))
                pending.chmod(0o600)
                pending.replace(result_path)
                return {}

            with self.assertRaises(a.ApprovedError) as error:
                a.perform(self.client(), state_recipe(result_path), '', journal, execute)
            self.assertNotIn(VALUE, str(error.exception))
            self.assertFalse(result_path.exists())

    def test_state_inventory_rejects_results_too_large_for_transport(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryFile(mode='w+') as journal:
            result_path = Path(tmp) / 'state-inventory.json'

            def execute(_, __):
                addresses = [f'aws_instance.worker["{"é" * 400}{index}"]' for index in range(1000)]
                pending = result_path.with_suffix('.new')
                pending.write_text(json.dumps({
                    'resource_addresses': addresses, 'count': len(addresses),
                }, ensure_ascii=False))
                pending.chmod(0o600)
                pending.replace(result_path)
                return {}

            with self.assertRaises(a.ApprovedError):
                a.perform(self.client(), state_recipe(result_path), '', journal, execute)
            self.assertFalse(result_path.exists())

    def test_state_inventory_failure_suppresses_both_streams(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryFile(mode='w+') as journal:
            script = '''import json, sys
inputs = json.load(sys.stdin)
print(' '.join(inputs.values()))
print(' '.join(inputs.values()), file=sys.stderr)
raise SystemExit(1)
'''
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with self.assertRaises(a.ApprovedError) as error:
                    a.perform(self.client(), state_recipe(Path(tmp) / 'result.json'), script, journal)
            visible = str(error.exception) + stdout.getvalue() + stderr.getvalue()
            self.assertNotIn(VALUE, visible)
            for value in STATE_VALUES.values():
                self.assertNotIn(value, visible)

    def test_state_inventory_timeout_suppresses_captured_credentials(self):
        child = Obj(
            returncode=None,
            kill=Mock(),
            communicate=Mock(side_effect=[
                a.subprocess.TimeoutExpired('state-list', 300, output=VALUE.encode(), stderr=VALUE.encode()),
                (b'', b''),
            ]),
        )
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryFile(mode='w+') as journal:
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(a.subprocess, 'Popen', return_value=child), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with self.assertRaises(a.ApprovedError) as error:
                    a.perform(self.client(), state_recipe(Path(tmp) / 'result.json'), '', journal)
            visible = str(error.exception) + stdout.getvalue() + stderr.getvalue()
            self.assertNotIn(VALUE, visible)
            child.kill.assert_called_once()

    def test_state_inventory_rejects_secret_in_result_without_echoing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / 'state-inventory.json'
            result_path.write_text(json.dumps({'resource_addresses': [VALUE], 'count': 1}))
            result_path.chmod(0o600)
            with self.assertRaises(a.ApprovedError) as error:
                a.read_state_inventory(result_path, {'state_passphrase': VALUE})
            self.assertNotIn(VALUE, str(error.exception))

    def test_state_inventory_rejects_escaped_secret_in_instance_key(self):
        value = 'synthetic\nstate"secret'
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / 'state-inventory.json'
            address = f'aws_instance.worker[{json.dumps(value)}]'
            result_path.write_text(json.dumps({'resource_addresses': [address], 'count': 1}))
            result_path.chmod(0o600)
            with self.assertRaises(a.ApprovedError) as error:
                a.read_state_inventory(result_path, {'state_passphrase': value})
            self.assertNotIn(value, str(error.exception))

    def test_state_inventory_recipe_requires_exact_state_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            directory = home / '.config/bws-operations'
            directory.mkdir(parents=True)
            script = home / 'state-inventory.py'
            script.write_text("print('{\"exports\":{}}')")
            script.chmod(0o600)
            digest = hashlib.sha256(script.read_bytes()).hexdigest()
            for inputs in ({}, {**state_recipe('/fixed/result.json')['inputs'], 'extra': {
                    'secret_id': IMPORTED, 'project_id': PROJECT}}):
                recipe = state_recipe('/fixed/result.json', str(script), digest)
                recipe['inputs'] = inputs
                config = directory / 'approved.json'
                config.write_text(json.dumps({'opentofu-state-inventory': recipe}))
                config.chmod(0o600)
                with self.assertRaises(a.ApprovedError):
                    a.load_recipe(home, 'opentofu-state-inventory')

    def test_state_inventory_result_path_cannot_alias_the_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            directory = home / '.config/bws-operations'
            directory.mkdir(parents=True)
            (home / 'subdirectory').mkdir()
            script = home / 'state-inventory.py'
            script.write_text("print('{\"exports\":{}}')")
            script.chmod(0o600)
            digest = hashlib.sha256(script.read_bytes()).hexdigest()
            result_path = home / 'subdirectory' / '..' / script.name
            config = directory / 'approved.json'
            config.write_text(json.dumps({
                'opentofu-state-inventory': state_recipe(result_path, str(script), digest),
            }))
            config.chmod(0o600)
            with self.assertRaises(a.ApprovedError):
                a.load_recipe(home, 'opentofu-state-inventory')

    def test_state_inventory_wrong_secret_or_project_never_executes(self):
        recipe = state_recipe('/fixed/state-inventory.json')
        for field in ('id', 'project_id'):
            client = self.client()
            fetched = Obj(id=SECRET, project_id=PROJECT, value=STATE_VALUES['state_access'])
            setattr(fetched, field, ORG)
            client.secrets().get.side_effect = lambda _secret_id, fetched=fetched: Obj(data=fetched)
            execute = Mock()
            with tempfile.TemporaryFile(mode='w+') as journal, self.assertRaises(a.ApprovedError):
                a.perform(client, recipe, '', journal, execute)
            execute.assert_not_called()

    def test_state_inventory_altered_script_hash_is_rejected_before_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            directory = home / '.config/bws-operations'
            directory.mkdir(parents=True)
            script = home / 'state-inventory.py'
            script.write_text("print('{\"exports\":{}}')")
            script.chmod(0o600)
            result_path = home / 'state-inventory.json'
            config = directory / 'approved.json'
            config.write_text(json.dumps({'opentofu-state-inventory': state_recipe(result_path, str(script))}))
            config.chmod(0o600)
            login = Mock()
            with self.assertRaises(a.ApprovedError):
                a.run(home, 'opentofu-state-inventory', login)
            login.assert_not_called()

    def test_state_inventory_announces_cleanup_before_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            directory = home / '.config/bws-operations'
            directory.mkdir(parents=True)
            script = home / 'state-inventory.py'
            script.write_text("print('{\"exports\":{}}')")
            script.chmod(0o600)
            digest = hashlib.sha256(script.read_bytes()).hexdigest()
            result_path = home / 'state-inventory.json'
            config = directory / 'approved.json'
            config.write_text(json.dumps({
                'opentofu-state-inventory': state_recipe(result_path, str(script), digest),
            }))
            config.chmod(0o600)
            announced = []

            def login(_region):
                self.assertEqual(announced, [str(result_path)])
                raise RuntimeError('stop before credential access')

            with self.assertRaises(RuntimeError):
                a.run(home, 'opentofu-state-inventory', login, announced.append)

    def test_values_stay_inside_operation_and_import(self):
        client = self.client()
        execute = Mock(return_value={'signing': 'synthetic-signing-material'})
        with tempfile.TemporaryFile(mode='w+') as journal:
            result = a.perform(client, RECIPE, 'reviewed code', journal, execute)
            self.assertEqual(result, {'status': 'completed', 'secret_ids': [IMPORTED]})
            execute.assert_called_once_with('reviewed code', {'bootstrap': VALUE})
            journal.seek(0)
            receipt = journal.read()
            self.assertNotIn(VALUE, receipt)
            self.assertNotIn('synthetic-signing-material', receipt)
            self.assertEqual(a.perform(client, RECIPE, 'reviewed code', journal, execute)['status'], 'recorded')
            execute.assert_called_once()
            client.secrets().get.assert_called_once_with(SECRET)

    def test_pending_operation_is_never_repeated(self):
        client = self.client()
        execute = Mock(side_effect=RuntimeError(VALUE))
        with tempfile.TemporaryFile(mode='w+') as journal:
            with self.assertRaises(RuntimeError): a.perform(client, RECIPE, '', journal, execute)
            with self.assertRaises(a.ApprovedError): a.perform(client, RECIPE, '', journal, execute)
            execute.assert_called_once()
            client.secrets().create.assert_not_called()

    def test_interrupted_receipt_append_fails_closed(self):
        client = self.client()
        execute = Mock(return_value={'signing': 'synthetic-signing-material'})
        with tempfile.TemporaryFile(mode='w+') as journal:
            a.perform(client, RECIPE, '', journal, execute)
            journal.seek(0, os.SEEK_END)
            journal.write('{"status":')
            journal.flush()
            with self.assertRaises(a.ApprovedError): a.perform(client, RECIPE, '', journal, execute)
            execute.assert_called_once()

    def test_wrong_project_does_not_execute(self):
        client = self.client()
        client.secrets().get.side_effect = lambda secret_id: Obj(
            data=Obj(id=secret_id, project_id=ORG, value=VALUE)
        )
        execute = Mock()
        with tempfile.TemporaryFile(mode='w+') as journal, self.assertRaises(a.ApprovedError):
            a.perform(client, RECIPE, '', journal, execute)
        execute.assert_not_called()

    def test_existing_export_name_does_not_read_values(self):
        client = self.client()
        client.secrets().list.return_value = Obj(data=Obj(data=[Obj(key='signing-v1')]))
        with tempfile.TemporaryFile(mode='w+') as journal, self.assertRaises(a.ApprovedError):
            a.perform(client, RECIPE, '', journal)
        client.secrets().get.assert_not_called()

    def test_unconfigured_export_is_rejected(self):
        client = self.client()
        with tempfile.TemporaryFile(mode='w+') as journal, self.assertRaises(a.ApprovedError):
            a.perform(client, RECIPE, '', journal, lambda *_: {'unexpected': VALUE})
        client.secrets().create.assert_not_called()

    def test_script_receives_no_inherited_credentials_or_arguments(self):
        script = '''import json, os, sys
assert len(sys.argv) == 1
assert 'BWS_ACCESS_TOKEN' not in os.environ
assert 'OTHER_SECRET' not in os.environ
assert 'HTTPS_PROXY' not in os.environ
data = json.load(sys.stdin)
print(data['bootstrap'], file=sys.stderr)
print(json.dumps({'exports': {'signing': data['bootstrap']}}))
'''
        with patch.dict(os.environ, {'BWS_ACCESS_TOKEN': 'synthetic-token', 'OTHER_SECRET': VALUE, 'HTTPS_PROXY': 'https://evil.invalid'}):
            self.assertEqual(a.execute_script(script, {'bootstrap': VALUE}), {'signing': VALUE})

    def test_script_failure_does_not_echo_output(self):
        with self.assertRaises(a.ApprovedError) as error:
            a.execute_script("import sys; print('synthetic-secret'); sys.exit(1)", {})
        self.assertNotIn('synthetic-secret', str(error.exception))

    def test_hash_mismatch_rejected_before_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            directory = home / '.config/bws-operations'
            directory.mkdir(parents=True)
            script = home / 'operation.py'
            script.write_text("print('reviewed')")
            script.chmod(0o600)
            config = directory / 'approved.json'
            config.write_text(json.dumps({'example': {**RECIPE, 'script': str(script)}}))
            config.chmod(0o600)
            login = Mock()
            with self.assertRaises(a.ApprovedError): a.run(home, 'example', login)
            login.assert_not_called()

    def test_arbitrary_cli_and_worker_failures_never_disclose(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(ops, 'provision_generated', side_effect=RuntimeError(VALUE)) as worker, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(ops.main(['run-approved', 'example', '--command', 'env']), 2)
            worker.assert_not_called()
            self.assertEqual(ops.main(['run-approved', 'example']), 1)
        self.assertNotIn(VALUE, stdout.getvalue() + stderr.getvalue())

    def test_parent_rejects_secret_bearing_result(self):
        def child(argv, **kwargs):
            os.write(kwargs['pass_fds'][0], json.dumps({'status': 'completed', 'secret_ids': [VALUE]}).encode())
            os.write(kwargs['pass_fds'][1], b'{"result_path":null}')
            return Obj(returncode=0, pid=12345, wait=Mock())
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(ops.subprocess, 'Popen', side_effect=child), patch.object(ops.os, 'killpg'), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(ops.main(['run-approved', 'example']), 1)
        self.assertNotIn(VALUE, stdout.getvalue() + stderr.getvalue())

    def test_parent_returns_large_inventory(self):
        addresses = [f'module.batch[{index}].aws_instance.worker' for index in range(1000)]
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / 'state-inventory.json'

            def child(_argv, **kwargs):
                os.write(kwargs['pass_fds'][0], json.dumps({
                    'status': 'completed',
                    'result': {'resource_addresses': addresses, 'count': len(addresses)},
                }).encode())
                os.write(kwargs['pass_fds'][1], json.dumps({
                    'result_path': str(result_path),
                }).encode())
                return Obj(returncode=0, pid=12345, wait=Mock())

            with patch.dict(os.environ, {}, clear=True), patch.object(
                    ops.subprocess, 'Popen', side_effect=child), patch.object(ops.os, 'killpg'):
                result = json.loads(ops.provision_generated('opentofu-state-inventory', approved=True))
            self.assertEqual(result['result']['count'], 1000)
            self.assertEqual(result['result']['resource_addresses'], addresses)

    def test_parent_waits_for_cleanup_path_before_releasing_token(self):
        captured_token_fds = []
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / 'state-inventory.json'

            def child(argv, **kwargs):
                self.assertEqual(argv[-1], 'run-approved')
                self.assertEqual(int(argv[-2]), kwargs['pass_fds'][1])
                token_fd = int(kwargs['env']['BWS_ACCESS_TOKEN_FD'])
                os.set_blocking(token_fd, False)
                with self.assertRaises(BlockingIOError):
                    os.read(token_fd, 1)
                os.set_blocking(token_fd, True)
                captured_token_fds.append(os.dup(token_fd))
                os.write(kwargs['pass_fds'][1], json.dumps({
                    'result_path': str(result_path),
                }).encode())
                os.write(kwargs['pass_fds'][0], json.dumps({
                    'status': 'completed',
                    'result': {'resource_addresses': [], 'count': 0},
                }).encode())
                return Obj(returncode=0, pid=12345, wait=Mock())

            variables = {
                'BWS_ACCESS_TOKEN': VALUE,
                'BWS_ACCESS_TOKEN_SOURCE': 'environment',
            }
            with patch.dict(os.environ, variables, clear=True), patch.object(
                    ops, 'keyring_available', return_value=False), patch.object(
                    ops.subprocess, 'Popen', side_effect=child), patch.object(ops.os, 'killpg'):
                result = json.loads(ops.provision_generated('opentofu-state-inventory', approved=True))
            self.assertEqual(result['result'], {'resource_addresses': [], 'count': 0})
            self.assertEqual(os.read(captured_token_fds[0], 8192), VALUE.encode())
            os.close(captured_token_fds[0])

    def test_parent_never_releases_token_without_cleanup_handshake(self):
        captured_token_fds = []

        def child(_argv, **kwargs):
            token_fd = int(kwargs['env']['BWS_ACCESS_TOKEN_FD'])
            captured_token_fds.append(os.dup(token_fd))
            return Obj(returncode=1, pid=12345, wait=Mock())

        variables = {
            'BWS_ACCESS_TOKEN': VALUE,
            'BWS_ACCESS_TOKEN_SOURCE': 'environment',
        }
        with patch.dict(os.environ, variables, clear=True), patch.object(
                ops, 'keyring_available', return_value=False), patch.object(
                ops.subprocess, 'Popen', side_effect=child), patch.object(ops.os, 'killpg'):
            with self.assertRaises(ops.OperationError):
                ops.provision_generated('opentofu-state-inventory', approved=True)
        self.assertEqual(os.read(captured_token_fds[0], 8192), b'')
        os.close(captured_token_fds[0])

    def test_completed_receipt_does_not_login(self):
        login = Mock(side_effect=AssertionError('must not authenticate'))
        with tempfile.TemporaryFile(mode='w+') as journal:
            journal.write(json.dumps({'binding': RECIPE, 'status': 'completed', 'secret_ids': [IMPORTED]}) + '\n')
            journal.flush()
            self.assertEqual(a.perform(None, RECIPE, '', journal, login=login)['status'], 'recorded')
        login.assert_not_called()

    def test_outer_timeout_kills_worker_and_removes_its_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / 'state-inventory.json'

            def launch_worker(_argv, **kwargs):
                result_path.write_text(VALUE)
                result_path.chmod(0o600)
                os.write(kwargs['pass_fds'][1], json.dumps({'result_path': str(result_path)}).encode())
                return Obj(pid=12345, wait=Mock(side_effect=[
                    ops.subprocess.TimeoutExpired('worker', 360), 0,
                ]))

            with patch.dict(os.environ, {}, clear=True), patch.object(
                    ops.subprocess, 'Popen', side_effect=launch_worker) as launch, patch.object(
                    ops.os, 'killpg') as kill:
                with self.assertRaises(ops.subprocess.TimeoutExpired):
                    ops.provision_generated('example', approved=True)
                self.assertTrue(launch.call_args.kwargs['start_new_session'])
                kill.assert_called_once_with(12345, ops.signal.SIGKILL)
                self.assertFalse(result_path.exists())

    def test_outer_timeout_preserves_a_result_that_is_not_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / 'state-inventory.json'

            def launch_worker(_argv, **kwargs):
                result_path.write_text('not a trusted result')
                result_path.chmod(0o644)
                os.write(kwargs['pass_fds'][1], json.dumps({
                    'result_path': str(result_path),
                }).encode())
                return Obj(pid=12345, wait=Mock(side_effect=[
                    ops.subprocess.TimeoutExpired('worker', 360), 0,
                ]))

            with patch.dict(os.environ, {}, clear=True), patch.object(
                    ops.subprocess, 'Popen', side_effect=launch_worker), patch.object(
                    ops.os, 'killpg'):
                with self.assertRaises(ops.subprocess.TimeoutExpired):
                    ops.provision_generated('example', approved=True)
            self.assertTrue(result_path.exists())


if __name__ == '__main__': unittest.main()
