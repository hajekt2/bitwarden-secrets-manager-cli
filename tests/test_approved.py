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
ORG = '33333333-3333-4333-8333-333333333333'
IMPORTED = '44444444-4444-4444-8444-444444444444'
VALUE = 'synthetic-secret-must-not-leak'
RECIPE = {'script': '/fixed/reviewed.py', 'sha256': 'a' * 64, 'region': 'us',
          'inputs': {'bootstrap': {'secret_id': SECRET, 'project_id': PROJECT}},
          'exports': {'signing': {'project_id': PROJECT, 'project_name': 'example', 'secret_name': 'signing-v1'}}}


class ApprovedTests(unittest.TestCase):
    def test_named_input_uses_identifiers_and_rejects_ambiguity(self):
        client = self.client()
        recipe = {**RECIPE, 'inputs': {'bootstrap': {'secret_name':'named-secret','project_id':PROJECT}}, 'exports':{}}
        client.secrets().list.return_value = Obj(data=Obj(data=[Obj(id=SECRET,key='named-secret')]))
        with tempfile.TemporaryFile(mode='w+') as journal:
            self.assertEqual(a.perform(client,recipe,'',journal,lambda *_:{} )['status'],'completed')
        client.secrets().get.assert_called_once_with(SECRET)
        client.secrets().get.reset_mock()
        client.secrets().list.return_value.data.data.append(Obj(id=IMPORTED,key='named-secret'))
        with tempfile.TemporaryFile(mode='w+') as journal, self.assertRaises(a.ApprovedError):
            a.perform(client,recipe,'',journal,lambda *_:{})
        client.secrets().get.assert_not_called()

    def client(self):
        client = Mock()
        client.projects().get.return_value = Obj(data=Obj(id=PROJECT, name='example', organization_id=ORG))
        client.secrets().list.return_value = Obj(data=Obj(data=[]))
        client.secrets().get.return_value = Obj(data=Obj(id=SECRET, project_id=PROJECT, value=VALUE))
        client.secrets().create.return_value = Obj(data=Obj(id=IMPORTED, project_id=PROJECT, organization_id=ORG, key='signing-v1', value='synthetic-signing-material'))
        return client

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
        client.secrets().get.return_value.data.project_id = ORG
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
            return Obj(returncode=0, pid=12345, wait=Mock())
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(ops.subprocess, 'Popen', side_effect=child), patch.object(ops.os, 'killpg'), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(ops.main(['run-approved', 'example']), 1)
        self.assertNotIn(VALUE, stdout.getvalue() + stderr.getvalue())

    def test_completed_receipt_does_not_login(self):
        login = Mock(side_effect=AssertionError('must not authenticate'))
        with tempfile.TemporaryFile(mode='w+') as journal:
            journal.write(json.dumps({'binding': RECIPE, 'status': 'completed', 'secret_ids': [IMPORTED]}) + '\n')
            journal.flush()
            self.assertEqual(a.perform(None, RECIPE, '', journal, login=login)['status'], 'recorded')
        login.assert_not_called()

    def test_outer_timeout_kills_worker_process_group(self):
        child = Obj(pid=12345, wait=Mock(side_effect=[ops.subprocess.TimeoutExpired('worker', 360), 0]))
        with patch.dict(os.environ, {}, clear=True), patch.object(ops.subprocess, 'Popen', return_value=child) as launch, patch.object(ops.os, 'killpg') as kill:
            with self.assertRaises(ops.subprocess.TimeoutExpired):
                ops.provision_generated('example', approved=True)
            self.assertTrue(launch.call_args.kwargs['start_new_session'])
            kill.assert_called_once_with(12345, ops.signal.SIGKILL)


if __name__ == '__main__': unittest.main()
