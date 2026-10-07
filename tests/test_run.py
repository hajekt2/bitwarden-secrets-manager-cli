import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('ops', Path(__file__).resolve().parents[1] / 'scripts/bws-operations.py')
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
ID = '11111111-2222-3333-4444-555555555555'
VALUE = 'synthetic-application-secret'


class RunTests(unittest.TestCase):
    def invoke(self, command):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {'PATH': '/usr/bin:/bin', 'BWS_SERVER_URL': 'ignored'}, clear=True), patch.object(ops, 'bws_executable', return_value='/trusted/bws'), patch.object(ops, 'keyring_token', return_value='synthetic-machine-token'), patch.object(ops, 'run_captured', return_value=json.dumps({'id': ID, 'value': VALUE}).encode()) as fetch, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ops.main(['run', '--secret', 'API_TOKEN=' + ID, '--', sys.executable, '-c', command])
        self.assertNotIn(VALUE, out.getvalue() + err.getvalue())
        self.assertNotIn('synthetic-machine-token', out.getvalue() + err.getvalue())
        return code, out.getvalue(), fetch

    def test_arbitrary_script_receives_only_application_secret(self):
        code, out, fetch = self.invoke("import os; assert os.environ['API_TOKEN'] == 'synthetic-application-secret'; assert not any(k.startswith('BWS_') for k in os.environ); print(os.environ['API_TOKEN'])")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {'status': 'completed'})
        self.assertEqual(fetch.call_args.args[0], ['/trusted/bws', 'secret', 'get', ID, '--output', 'json'])

    def test_failure_output_suppressed(self):
        code, out, _ = self.invoke("import os, sys; print(os.environ['API_TOKEN'], file=sys.stderr); sys.exit(3)")
        self.assertEqual(code, 1)
        self.assertEqual(out, '')

    def test_invalid_bindings_rejected_before_lookup(self):
        with patch.object(ops, 'keyring_token') as token:
            for args in [[], ['--secret', 'API_TOKEN=invalid', '--', 'true'], ['--secret', 'BWS_ACCESS_TOKEN=' + ID, '--', 'true'], ['--secret', 'API_TOKEN=' + ID, '--timeout', '0', '--', 'true']]:
                with self.subTest(args=args), self.assertRaises(ops.OperationError):
                    ops.run_script(args)
            token.assert_not_called()

    def test_timeout_output_suppressed(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(ops, 'bws_executable', return_value='/trusted/bws'), patch.object(ops, 'keyring_token', return_value='synthetic-machine-token'), patch.object(ops, 'run_captured', return_value=json.dumps({'id': ID, 'value': VALUE}).encode()), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ops.main(['run', '--secret', 'API_TOKEN=' + ID, '--timeout', '1', '--', sys.executable, '-c', 'import time; time.sleep(10)'])
        self.assertEqual(code, 1)
        self.assertNotIn(VALUE, out.getvalue() + err.getvalue())
