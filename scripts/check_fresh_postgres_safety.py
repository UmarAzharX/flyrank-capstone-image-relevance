"""Offline checks for temporary-container isolation and cleanup."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import verify_fresh_postgres as setup

TOKEN = 'a' * 32
CONTAINER = 'b' * 64


class FreshPostgresSafetyChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        (self.project / 'alembic.ini').write_text('test')
        (self.project / 'data').mkdir()
        (self.project / 'data/images.json').write_text('[]')
        self.report_path = self.project / 'report.json'
        self.commands = []
        self.fail_seed = False
        self.wrong_owner = False
        self.seed_count = 0
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def fake_run(self, command, **options):
        self.commands.append((command, options))
        if command[:3] == ['docker', 'image', 'inspect']:
            output = 'linux\n'
        elif command[:2] == ['docker', 'run']:
            output = CONTAINER
        elif command[:2] == ['docker', 'inspect']:
            output = json.dumps({'5432/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '55439'}]}) if 'NetworkSettings' in command[3] else ('different-owner' if self.wrong_owner else TOKEN)
        elif 'scripts.seed' in command:
            if self.fail_seed:
                raise RuntimeError('simulated seed failure')
            self.seed_count += 1
            output = 'Created images: 50\nSkipped existing images: 0\n' if self.seed_count == 1 else 'Created images: 0\nSkipped existing images: 50\n'
        elif '--inspect-database' in command:
            output = json.dumps({'checks': [{'name': 'offline_orchestration_fixture', 'passed': True}], 'images': 50, 'schema_differences': 0, 'ai_calls': 0})
        else:
            output = ''
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr='')

    def run_check(self):
        with patch.object(setup, 'run_command', side_effect=self.fake_run), patch.object(setup.uuid, 'uuid4') as uid, patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            uid.return_value.hex = TOKEN
            return setup.verify(self.project, report_path=self.report_path)

    def test_environment_override_disables_ai_without_changing_parent(self):
        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://original/private', 'GEMINI_API_KEY': 'parent-fixture-key'}):
            child = setup.scratch_environment(55439, TOKEN)
            self.assertTrue(child['DATABASE_URL'].endswith(':55439/flyrank_setup_check'))
            self.assertEqual(child['GEMINI_API_KEY'], '')
            self.assertEqual(child['AI_MAX_CALLS'], '0')
            self.assertEqual(os.environ['DATABASE_URL'], 'postgresql://original/private')
            self.assertEqual(os.environ['GEMINI_API_KEY'], 'parent-fixture-key')

    def test_success_uses_localhost_temporary_container_and_removes_only_its_id(self):
        report = self.run_check()
        self.assertTrue(report['passed'])
        self.assertTrue(report['container_removed'])
        run = next(c for c, _ in self.commands if c[:2] == ['docker', 'run'])
        self.assertEqual(run[run.index('--publish') + 1], '127.0.0.1::5432')
        self.assertIn('--pull=never', run)
        self.assertIn('--tmpfs', run)
        removes = [c for c, _ in self.commands if c[:2] == ['docker', 'rm']]
        self.assertEqual(removes, [['docker', 'rm', '--force', CONTAINER]])
        children = [(c, o) for c, o in self.commands if '-m' in c or '--inspect-database' in c]
        self.assertEqual(len(children), 5)
        self.assertTrue(all(o['env']['AI_MAX_CALLS'] == '0' and not o['env']['GEMINI_API_KEY'] for _, o in children))
        self.assertEqual(json.loads(self.report_path.read_text())['ai_calls'], 0)

    def test_failed_seed_still_cleans_up_and_reports_failure(self):
        self.fail_seed = True
        report = self.run_check()
        self.assertFalse(report['passed'])
        self.assertEqual(report['failed_stage'], 'Seed image records')
        self.assertTrue(report['container_removed'])
        self.assertFalse(any('--inspect-database' in c for c, _ in self.commands))

    def test_owner_mismatch_prevents_container_removal(self):
        self.wrong_owner = True
        report = self.run_check()
        self.assertFalse(report['passed'])
        self.assertFalse(report['container_removed'])
        self.assertFalse(any(c[:2] == ['docker', 'rm'] for c, _ in self.commands))


if __name__ == '__main__':
    unittest.main()
