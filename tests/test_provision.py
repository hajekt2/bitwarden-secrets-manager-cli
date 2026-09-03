import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]

def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

p = load('provision', 'provision.py')
ops = load('ops', 'bws-operations.py')
PROJECT = '11111111-2222-3333-4444-555555555555'
ORG = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
SECRET = '12345678-abcd-abcd-abcd-123456789abc'
RECIPE = {'project_id': PROJECT, 'project_name': 'example', 'secret_name': 'bootstrap', 'region': 'us', 'fields': {'PASSWORD': 32}}

class ProvisionTests(unittest.TestCase):
    def client(self):
        client = Mock()
        client.projects().get.return_value = Obj(data=Obj(id=PROJECT, name='example', organization_id=ORG))
        client.secrets().list.return_value = Obj(data=Obj(data=[]))
        def create(org, key, value, note, projects):
            self.assertEqual(projects, [PROJECT])
            return Obj(data=Obj(id=SECRET, organization_id=org, project_id=PROJECT, key=key, value=value))
        client.secrets().create.side_effect = create
        return client

    def test_create_contains_no_values_in_receipt_and_retry_is_read_only(self):
        client = self.client()
        with tempfile.TemporaryFile(mode='w+') as journal:
            result = p.provision(client, RECIPE, journal)
            self.assertEqual(result, {'status': 'created', 'secret_id': SECRET})
            value = client.secrets().create.call_args.args[2]
            self.assertEqual(len(json.loads(value)['PASSWORD']), 64)
            journal.seek(0)
            self.assertNotIn(json.loads(value)['PASSWORD'], journal.read())
            self.assertEqual(p.provision(client, RECIPE, journal)['status'], 'recorded')
            client.secrets().create.assert_called_once()
            client.secrets().get.assert_not_called()

    def test_uncertain_write_is_never_retried(self):
        client = self.client()
        client.secrets().create.side_effect = RuntimeError('SYNTHETIC_SECRET')
        with tempfile.TemporaryFile(mode='w+') as journal:
            with self.assertRaises(RuntimeError):
                p.provision(client, RECIPE, journal)
            with self.assertRaises(p.ProvisionError):
                p.provision(client, RECIPE, journal)
            client.secrets().create.assert_called_once()

    def test_existing_name_or_wrong_project_never_creates(self):
        for wrong_project in (False, True):
            client = self.client()
            if wrong_project:
                client.projects().get.return_value.data.name = 'wrong'
            else:
                client.secrets().list.return_value.data.data = [Obj(key='bootstrap')]
            with tempfile.TemporaryFile(mode='w+') as journal, self.assertRaises(p.ProvisionError):
                p.provision(client, RECIPE, journal)
            client.secrets().create.assert_not_called()

    def test_bad_recipe_rejected_before_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            directory = home / '.config/bws-operations'
            directory.mkdir(parents=True)
            config = directory / 'recipes.json'
            for recipe in ({**RECIPE, 'region': 'https://evil.invalid'}, {**RECIPE, 'command': 'env'}, {**RECIPE, 'fields': {'PASSWORD': 1}}):
                config.write_text(json.dumps({'example': recipe}))
                config.chmod(0o600)
                login = Mock()
                with self.assertRaises(p.ProvisionError):
                    p.run(home, 'example', login)
                login.assert_not_called()

    def test_public_recipe_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'recipe'
            path.write_text('{}')
            path.chmod(0o644)
            with self.assertRaises(p.ProvisionError): p.private_json(path)
            link = Path(tmp) / 'link'
            link.symlink_to(path)
            with self.assertRaises(OSError): p.private_json(link)

    def test_recipe_aliases_share_receipt_and_changed_fields_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            directory = home / '.config/bws-operations'
            directory.mkdir(parents=True)
            config = directory / 'recipes.json'
            config.write_text(json.dumps({'first':RECIPE,'alias':RECIPE,'changed':{**RECIPE,'fields':{'PASSWORD':64}}}))
            config.chmod(0o600)
            client = self.client()
            login = Mock(return_value=client)
            self.assertEqual(p.run(home,'first',login)['status'],'created')
            self.assertEqual(p.run(home,'alias',login)['status'],'recorded')
            with self.assertRaises(p.ProvisionError): p.run(home,'changed',login)
            client.secrets().create.assert_called_once()
            self.assertEqual(len(list((home / '.local/state/bws-operations').glob('*.json'))),1)

    def test_worker_exception_never_reaches_terminal(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(ops, 'provision_generated', side_effect=RuntimeError('SYNTHETIC_SECRET')), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(ops.main(['provision-generated', 'example']), 1)
        self.assertNotIn('SYNTHETIC_SECRET', stdout.getvalue() + stderr.getvalue())

    def test_bad_cli_arguments_never_launch_worker(self):
        with patch.object(ops, 'provision_generated') as worker, contextlib.redirect_stderr(io.StringIO()):
            for args in (['provision-generated', '../example'], ['provision-generated','example','--url','evil'], ['provision-generated']):
                self.assertEqual(ops.main(args), 2)
            worker.assert_not_called()

    def test_inherited_token_rejected(self):
        with patch.dict(os.environ, {'BWS_ACCESS_TOKEN': 'SYNTHETIC_SECRET'}), patch.object(ops.subprocess, 'Popen') as child:
            with self.assertRaises(ops.OperationError): ops.provision_generated('example')
            child.assert_not_called()

    def test_parent_suppresses_streams_and_filters_receipt(self):
        def child(argv, **kwargs):
            self.assertEqual(kwargs['stdout'], subprocess.DEVNULL)
            self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
            self.assertNotIn('BWS_ACCESS_TOKEN', kwargs['env'])
            self.assertNotIn('OTHER_SECRET', kwargs['env'])
            self.assertNotIn('HTTPS_PROXY', kwargs['env'])
            self.assertEqual(argv[1], '-I')
            os.write(kwargs['pass_fds'][0], json.dumps({'status':'created','secret_id':SECRET}).encode())
            return Obj(returncode=0, pid=12345, wait=Mock())
        with patch.dict(os.environ, {'OTHER_SECRET':'SYNTHETIC_SECRET','HTTPS_PROXY':'https://evil.invalid'}, clear=True), patch.object(ops.subprocess, 'Popen', side_effect=child), patch.object(ops.os, 'killpg'):
            self.assertEqual(json.loads(ops.provision_generated('example')), {'status':'created','secret_id':SECRET})

    def test_malformed_worker_receipt_is_not_echoed(self):
        def child(argv, **kwargs):
            os.write(kwargs['pass_fds'][0], b'{"status":"created","secret_id":"SYNTHETIC_SECRET"}')
            return Obj(returncode=0, pid=12345, wait=Mock())
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(ops.subprocess, 'Popen', side_effect=child), patch.object(ops.os, 'killpg'), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(ops.main(['provision-generated','example']),1)
        self.assertNotIn('SYNTHETIC_SECRET', stdout.getvalue()+stderr.getvalue())

if __name__ == '__main__': unittest.main()
