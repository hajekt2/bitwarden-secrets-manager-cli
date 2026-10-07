import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('operations', ROOT / 'scripts/bws-operations.py')
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
TOKEN = 'synthetic-access-token-for-tests'
PROJECT = {'id': '11111111-2222-3333-4444-555555555555', 'name': 'example'}
ORG = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ops.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_denied_forms_never_access_credentials(self):
        denied = [
            ['bws', 'secret', 'list'],
            ['bws', 'secret', 'get', PROJECT['id']],
            ['bws', 'secret', 'list', '--output', 'none'],
            ['bws', 'run', '--', 'env'],
            ['env'], ['sh', '-c', 'env'],
            ['/usr/bin/bws', 'project', 'list', '--output', 'none'],
            ['bws', 'project', 'list', '--output', 'none', '--server-url', 'https://example.invalid'],
            ['projects', '--server-url', 'https://example.invalid'],
            ['check-auth', '--help'], [],
            ['secret-names'], ['secret-names', 'ap-south-1'],
        ]
        with patch.object(ops, 'execute') as execute:
            for args in denied:
                with self.subTest(args=args):
                    self.assertEqual(self.invoke(args)[0], 2)
            execute.assert_not_called()

    def test_declared_environment_source_wins_on_keyring_capable_host(self):
        variables = {'BWS_ACCESS_TOKEN': TOKEN, 'BWS_ACCESS_TOKEN_SOURCE': 'environment'}
        with patch.dict(os.environ, variables, clear=True), patch.object(ops, 'keyring_available', return_value=True), patch.object(ops, 'keyring_token') as keyring, patch.object(
                ops, 'bws_executable', return_value='/trusted/bws'), patch.object(ops, 'run_captured', return_value=b'[]') as run:
            code, out, err = self.invoke(['check-auth'])
        self.assertEqual(code, 0)
        keyring.assert_not_called()
        self.assertNotIn(TOKEN, out + err)
        self.assertEqual(run.call_args.args[1]['BWS_ACCESS_TOKEN'], TOKEN)

    def test_keyring_capable_host_rejects_undeclared_environment_token(self):
        variables = {'BWS_ACCESS_TOKEN': TOKEN}
        with patch.dict(os.environ, variables, clear=True), patch.object(ops, 'keyring_available', return_value=True), patch.object(ops, 'keyring_token') as lookup, patch.object(ops, 'run_captured') as run:
            code, out, err = self.invoke(['check-auth'])
        self.assertEqual(code, 1)
        self.assertNotIn(TOKEN, out + err)
        self.assertIn('denied', err)
        lookup.assert_not_called()
        run.assert_not_called()

    def test_declared_source_without_token_falls_back_to_keyring(self):
        variables = {'BWS_ACCESS_TOKEN_SOURCE': 'environment'}
        with patch.dict(os.environ, variables, clear=True), patch.object(ops, 'keyring_available', return_value=True), patch.object(ops, 'keyring_token', return_value=TOKEN), patch.object(
                ops, 'bws_executable', return_value='/trusted/bws'), patch.object(ops, 'run_captured', return_value=b'[]') as run:
            code, out, err = self.invoke(['check-auth'])
        self.assertEqual(code, 0)
        self.assertNotIn(TOKEN, out + err)
        self.assertEqual(run.call_args.args[1]['BWS_ACCESS_TOKEN'], TOKEN)

    def test_keyring_unavailable_host_requires_explicit_opt_in(self):
        with patch.dict(os.environ, {'BWS_ACCESS_TOKEN': TOKEN}), patch.object(ops, 'keyring_available', return_value=False), patch.object(ops, 'keyring_token') as lookup:
            code, out, err = self.invoke(['check-auth'])
        self.assertEqual(code, 1)
        self.assertIn('No credential source is available', err)
        self.assertNotIn(TOKEN, out + err)
        lookup.assert_not_called()

    def test_exact_legacy_auth_form_is_supported(self):
        with patch.object(ops, 'execute', return_value='ok') as execute:
            self.assertEqual(self.invoke(['bws', 'project', 'list', '--output', 'none'])[0], 0)
        execute.assert_called_once_with('check-auth', None)

    def test_token_is_only_in_bws_child_environment(self):
        parent = {
            'PATH': '/untrusted', 'BWS_ACCESS_TOKEN': TOKEN,
            'BWS_ACCESS_TOKEN_SOURCE': 'environment',
            'BWS_SERVER_URL': 'https://example.invalid', 'PYTHONPATH': '/untrusted',
            'OTHER_SECRET': 'unrelated',
        }
        with patch.dict(os.environ, parent), patch.object(ops, 'keyring_available', return_value=False), patch.object(ops, 'bws_executable', return_value='/trusted/bws'), patch.object(ops, 'run_captured', return_value=b'') as run:
            code, out, err = self.invoke(['check-auth'])
            self.assertEqual(os.environ['BWS_ACCESS_TOKEN'], TOKEN)
        self.assertEqual(code, 0)
        request = run.call_args
        self.assertEqual(request.args[0], ['/trusted/bws', 'project', 'list', '--output', 'none'])
        self.assertEqual(request.args[1]['BWS_ACCESS_TOKEN'], TOKEN)
        for key in ('BWS_ACCESS_TOKEN_SOURCE', 'BWS_SERVER_URL', 'PYTHONPATH', 'OTHER_SECRET'):
            self.assertNotIn(key, request.args[1])
        self.assertEqual(request.args[1]['PATH'], '/usr/bin:/bin')
        self.assertNotIn(TOKEN, out + err)

    def test_auth_discards_success_output(self):
        with patch.object(ops, 'keyring_available', return_value=True), patch.object(ops, 'bws_executable', return_value='/trusted/bws'), patch.object(ops, 'keyring_token', return_value=TOKEN), patch.object(ops, 'run_captured', return_value=TOKEN.encode()):
            code, out, err = self.invoke(['check-auth'])
        self.assertEqual(code, 0)
        self.assertNotIn(TOKEN, out + err)

    def test_projects_returns_only_selected_metadata(self):
        payload = json.dumps([{**PROJECT, 'value': 'synthetic-secret-value', 'note': TOKEN}]).encode()
        with patch.object(ops, 'keyring_available', return_value=True), patch.object(ops, 'bws_executable', return_value='/trusted/bws'), patch.object(ops, 'keyring_token', return_value=TOKEN), patch.object(ops, 'run_captured', return_value=payload):
            code, out, err = self.invoke(['projects'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [PROJECT])
        self.assertNotIn(TOKEN, out + err)
        self.assertNotIn('synthetic-secret-value', out + err)

    def test_bad_project_response_is_not_echoed(self):
        payloads = [TOKEN.encode(), json.dumps([{'id': PROJECT['id'], 'name': TOKEN}]).encode(), b'{}', b'[{"name": "missing id"}]']
        for payload in payloads:
            with self.subTest(payload=payload), patch.object(ops, 'keyring_available', return_value=True), patch.object(ops, 'bws_executable', return_value='/trusted/bws'), patch.object(ops, 'keyring_token', return_value=TOKEN), patch.object(ops, 'run_captured', return_value=payload):
                code, out, err = self.invoke(['projects'])
            self.assertEqual(code, 1)
            self.assertNotIn(TOKEN, out + err)

    def test_child_failure_does_not_expose_either_stream(self):
        result = subprocess.CompletedProcess([], 1, stdout=TOKEN.encode(), stderr=TOKEN.encode())
        with patch.object(ops.subprocess, 'run', return_value=result):
            with self.assertRaises(ops.OperationError) as error:
                ops.run_captured(['/trusted/bws'], {})
        self.assertNotIn(TOKEN, str(error.exception))

    def test_timeout_does_not_expose_captured_data(self):
        error = subprocess.TimeoutExpired('bws', 30, output=TOKEN, stderr=TOKEN)
        with patch.object(ops.subprocess, 'run', side_effect=error):
            with self.assertRaises(ops.OperationError) as caught:
                ops.run_captured(['/trusted/bws'], {})
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_missing_keyring_token_fails(self):
        with patch.object(ops, 'run_captured', return_value=b''):
            with self.assertRaises(ops.OperationError):
                ops.keyring_token({})

    def test_vault_rejection_is_distinct_from_missing_credential_source(self):
        failure = subprocess.CompletedProcess([], 1, stdout=TOKEN.encode(), stderr=TOKEN.encode())
        variables = {'BWS_ACCESS_TOKEN': TOKEN, 'BWS_ACCESS_TOKEN_SOURCE': 'environment'}
        with patch.dict(os.environ, variables), patch.object(ops, 'keyring_available', return_value=False), patch.object(ops, 'bws_executable', return_value='/trusted/bws'), patch.object(ops.subprocess, 'run', return_value=failure):
            code, out, err = self.invoke(['check-auth'])
        self.assertEqual(code, 1)
        self.assertIn('Credential was found', err)
        self.assertIn('vault request failed or rejected it', err)
        self.assertNotIn(TOKEN, out + err)

    def test_secret_name_enumeration_uses_identifier_listing_only(self):
        client = Mock()
        client.secrets().list.return_value = Obj(data=Obj(data=[
            Obj(id='22222222-2222-4222-8222-222222222222', key='database-url',
                project_ids=[PROJECT['id']]),
        ]))
        projects = [{**PROJECT, 'organization_id': ORG}]
        self.assertEqual(
            ops.identifier_secret_names(client, projects),
            (1, [{'project': 'example', 'key': 'database-url'}]),
        )
        client.secrets().list.assert_called_once_with(ORG)
        client.secrets().get.assert_not_called()
        client.secrets().create.assert_not_called()

    def test_secret_name_enumeration_disambiguates_duplicate_project_names(self):
        second = '66666666-7777-4888-8999-000000000000'
        client = Mock()
        client.secrets().list.return_value = Obj(data=Obj(data=[
            Obj(key='shared-key', project_ids=[PROJECT['id'], second]),
        ]))
        projects = [
            {**PROJECT, 'organization_id': ORG},
            {'id': second, 'name': PROJECT['name'], 'organization_id': ORG},
        ]
        self.assertEqual(ops.identifier_secret_names(client, projects), (
            1,
            [
                {'project': 'example', 'key': 'shared-key', 'project_id': PROJECT['id']},
                {'project': 'example', 'key': 'shared-key', 'project_id': second},
            ],
        ))

    def test_secret_name_enumeration_surfaces_unattributed_projects(self):
        ghost = '99999999-8888-4777-8666-555555555555'
        client = Mock()
        client.secrets().list.return_value = Obj(data=Obj(data=[
            Obj(key='listed-key', project_ids=[PROJECT['id']]),
            Obj(key='orphan-key', project_ids=[ghost]),
            Obj(key='detached-key', project_ids=[]),
        ]))
        projects = [{**PROJECT, 'organization_id': ORG}]
        self.assertEqual(ops.identifier_secret_names(client, projects), (
            3,
            [
                {'project': 'example', 'key': 'listed-key'},
                {'project': 'unattributed:' + ghost, 'key': 'orphan-key'},
                {'project': 'unattributed:no-project', 'key': 'detached-key'},
            ],
        ))

    def test_secret_name_enumeration_rejects_marker_like_project_names(self):
        client = Mock()
        projects = [{'id': PROJECT['id'], 'name': 'unattributed:example', 'organization_id': ORG}]
        with self.assertRaises(ops.OperationError):
            ops.identifier_secret_names(client, projects)
        client.secrets.assert_not_called()

    def test_secret_names_success_and_failure_never_return_token(self):
        safe = json.dumps({'count': 1, 'secrets': [{'project': 'example', 'key': 'database-url'}]}).encode()
        success = subprocess.CompletedProcess([], 0, stdout=safe, stderr=TOKEN.encode())
        failure = subprocess.CompletedProcess([], 1, stdout=TOKEN.encode(), stderr=TOKEN.encode())
        with patch.object(ops.Path, 'is_file', return_value=True), patch.object(ops.os, 'access', return_value=True), patch.object(ops.subprocess, 'run', return_value=success):
            result = ops.sdk_secret_names('us', TOKEN, [{**PROJECT, 'organization_id': ORG}], {'HOME': '/fixed'})
        self.assertEqual(json.loads(result), {'count': 1, 'secrets': [{'project': 'example', 'key': 'database-url'}]})
        self.assertNotIn(TOKEN, result)
        with patch.object(ops.Path, 'is_file', return_value=True), patch.object(ops.os, 'access', return_value=True), patch.object(ops.subprocess, 'run', return_value=failure):
            with self.assertRaises(ops.OperationError) as error:
                ops.sdk_secret_names('us', TOKEN, [{**PROJECT, 'organization_id': ORG}], {'HOME': '/fixed'})
        self.assertNotIn(TOKEN, str(error.exception))

    def test_secret_names_report_shape_fails_closed(self):
        projects = [{**PROJECT, 'organization_id': ORG}]
        rejected = [
            b'[]',
            json.dumps({'count': 1}).encode(),
            json.dumps({'count': 2, 'secrets': []}).encode(),
            json.dumps({'count': 0, 'secrets': [{'project': 'example', 'key': 'k'}]}).encode(),
            json.dumps({'count': True, 'secrets': []}).encode(),
            json.dumps({'count': 1, 'secrets': [{'project': 'unlisted', 'key': 'k'}]}).encode(),
            json.dumps({'count': 1, 'secrets': [{'project': 'unattributed:' + ORG, 'key': 'k', 'project_id': PROJECT['id']}]}).encode(),
        ]
        for stdout in rejected:
            result = subprocess.CompletedProcess([], 0, stdout=stdout, stderr=b'')
            with patch.object(ops.Path, 'is_file', return_value=True), patch.object(ops.os, 'access', return_value=True), patch.object(ops.subprocess, 'run', return_value=result):
                with self.assertRaises(ops.OperationError):
                    ops.sdk_secret_names('us', TOKEN, projects, {'HOME': '/fixed'})
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps({'count': 1, 'secrets': [{'project': 'unattributed:' + ORG, 'key': 'orphan-key'}]}).encode(), stderr=b'')
        with patch.object(ops.Path, 'is_file', return_value=True), patch.object(ops.os, 'access', return_value=True), patch.object(ops.subprocess, 'run', return_value=result):
            self.assertEqual(
                json.loads(ops.sdk_secret_names('us', TOKEN, projects, {'HOME': '/fixed'})),
                {'count': 1, 'secrets': [{'project': 'unattributed:' + ORG, 'key': 'orphan-key'}]},
            )

    def test_secret_names_cli_uses_no_bulk_secret_command(self):
        project_payload = json.dumps([{**PROJECT, 'organizationId': ORG}]).encode()
        variables = {'BWS_ACCESS_TOKEN': TOKEN, 'BWS_ACCESS_TOKEN_SOURCE': 'environment'}
        with patch.dict(os.environ, variables), patch.object(ops, 'keyring_available', return_value=False), patch.object(ops, 'bws_executable', return_value='/trusted/bws'), patch.object(ops, 'run_captured', return_value=project_payload) as run, patch.object(ops, 'sdk_secret_names', return_value='{"count": 0, "secrets": []}') as sdk:
            code, out, err = self.invoke(['secret-names', 'us'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {'count': 0, 'secrets': []})
        self.assertEqual(run.call_args.args[0], ['/trusted/bws', 'project', 'list', '--output', 'json'])
        self.assertNotIn('secret', run.call_args.args[0])
        sdk.assert_called_once()
        self.assertNotIn(TOKEN, out + err)

    def test_removed_helpers_fail_closed(self):
        for name in ('list-secret-metadata.sh', 'safe-bws-run.sh', 'sync-secret-to-vercel.py'):
            launcher = '/usr/bin/python3' if name.endswith('.py') else '/bin/sh'
            result = subprocess.run([launcher, str(ROOT / 'scripts' / name), TOKEN], capture_output=True, text=True, env={'PATH': '/nonexistent'})
            self.assertEqual(result.returncode, 2, name)
            self.assertNotIn(TOKEN, result.stdout + result.stderr)

    def test_shell_entrypoint_rejects_raw_bws(self):
        result = subprocess.run(['/bin/sh', str(ROOT / 'scripts/with-bws-token.sh'), 'bws', 'secret', 'list'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Operation denied', result.stderr)


if __name__ == '__main__':
    unittest.main()
