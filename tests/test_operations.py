import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('operations', ROOT / 'scripts/bws-operations.py')
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
TOKEN = 'synthetic-access-token-for-tests'
PROJECT = {'id': '11111111-2222-3333-4444-555555555555', 'name': 'example'}


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
        ]
        with patch.object(ops, 'execute') as execute:
            for args in denied:
                with self.subTest(args=args):
                    self.assertEqual(self.invoke(args)[0], 2)
            execute.assert_not_called()

    def test_inherited_token_is_rejected_without_keyring_lookup(self):
        with patch.dict(os.environ, {'BWS_ACCESS_TOKEN': TOKEN}), patch.object(ops, 'keyring_token') as lookup:
            code, out, err = self.invoke(['check-auth'])
        self.assertEqual(code, 1)
        self.assertNotIn(TOKEN, out + err)
        lookup.assert_not_called()

    def test_exact_legacy_auth_form_is_supported(self):
        with patch.object(ops, 'execute', return_value='ok') as execute:
            self.assertEqual(self.invoke(['bws', 'project', 'list', '--output', 'none'])[0], 0)
        execute.assert_called_once_with('check-auth')

    def test_token_is_only_in_bws_child_environment(self):
        parent = {'PATH': '/untrusted', 'BWS_SERVER_URL': 'https://example.invalid', 'PYTHONPATH': '/untrusted', 'OTHER_SECRET': 'unrelated'}
        with patch.dict(os.environ, parent), patch.object(ops, 'bws_executable', return_value='/trusted/bws'), patch.object(ops, 'run_captured', side_effect=[TOKEN.encode(), b''] ) as run:
            code, out, err = self.invoke(['check-auth'])
            self.assertNotIn('BWS_ACCESS_TOKEN', os.environ)
        self.assertEqual(code, 0)
        lookup, request = run.call_args_list
        self.assertEqual(lookup.args[0], ['/usr/bin/secret-tool', 'lookup', 'service', 'bws', 'account', 'access-token'])
        self.assertNotIn('BWS_ACCESS_TOKEN', lookup.args[1])
        self.assertEqual(request.args[0], ['/trusted/bws', 'project', 'list', '--output', 'none'])
        self.assertEqual(request.args[1]['BWS_ACCESS_TOKEN'], TOKEN)
        for key in ('BWS_SERVER_URL', 'PYTHONPATH', 'OTHER_SECRET'):
            self.assertNotIn(key, request.args[1])
        self.assertEqual(request.args[1]['PATH'], '/usr/bin:/bin')
        self.assertNotIn(TOKEN, out + err)

    def test_auth_discards_success_output(self):
        with patch.object(ops, 'bws_executable', return_value='/trusted/bws'), patch.object(ops, 'keyring_token', return_value=TOKEN), patch.object(ops, 'run_captured', return_value=TOKEN.encode()):
            code, out, err = self.invoke(['check-auth'])
        self.assertEqual(code, 0)
        self.assertNotIn(TOKEN, out + err)

    def test_projects_returns_only_selected_metadata(self):
        payload = json.dumps([{**PROJECT, 'value': 'synthetic-secret-value', 'note': TOKEN}]).encode()
        with patch.object(ops, 'bws_executable', return_value='/trusted/bws'), patch.object(ops, 'keyring_token', return_value=TOKEN), patch.object(ops, 'run_captured', return_value=payload):
            code, out, err = self.invoke(['projects'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [PROJECT])
        self.assertNotIn(TOKEN, out + err)
        self.assertNotIn('synthetic-secret-value', out + err)

    def test_bad_project_response_is_not_echoed(self):
        payloads = [TOKEN.encode(), json.dumps([{'id': PROJECT['id'], 'name': TOKEN}]).encode(), b'{}', b'[{"name": "missing id"}]']
        for payload in payloads:
            with self.subTest(payload=payload), patch.object(ops, 'bws_executable', return_value='/trusted/bws'), patch.object(ops, 'keyring_token', return_value=TOKEN), patch.object(ops, 'run_captured', return_value=payload):
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
