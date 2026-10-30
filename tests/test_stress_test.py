"""Verify independent stress jobs, environment loading and per-project port rendering."""

from contextlib import redirect_stdout
import errno
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.project.initialize import initialize_project
from infrastructure.stages.backend.runtime import prepare_runtime
from infrastructure.stages.frontend.ui.runtime import prepare_frontend
from scripts import stress_test


class StressTest(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def arguments(self, *extra):
        source = self.root / 'input'
        source.mkdir(exist_ok=True)
        (source / 'requirements.yaml').write_text('id: ROOT\nchildren: []\n')
        env = self.root / '.env'
        env.write_text('MODEL=stress-model\nOPENAI_API_KEY=test-secret\nPORT=12345\n')
        return stress_test.parse_args(['--input', str(source), '--output', str(self.root / 'batch'),
            '--env-file', str(env), *extra])

    def test_custom_ports_survive_later_runtime_preparation_and_do_not_modify_shared_templates(self):
        for index, port in enumerate((33000, 33049)):
            output = self.root / str(index)
            initialize_project(output, port=port)
            initialize_project(output)
            prepare_runtime(output, {})
            prepare_frontend(output)
            self.assertIn(f'process.env.PORT ?? "{port}"', (output / 'backend/src/server.ts').read_text())
            self.assertIn(f'http://127.0.0.1:{port}', (output / 'frontend/vite.config.ts').read_text())
        default = self.root / 'default'
        initialize_project(default)
        self.assertIn('process.env.PORT ?? "3000"', (default / 'backend/src/server.ts').read_text())

    def test_fifty_detached_jobs_have_distinct_ports_logs_outputs_and_dotenv_environment(self):
        args = self.arguments('--model-log')
        ports = list(range(33000, 33050))
        with patch.object(stress_test, 'available_ports', return_value=ports), \
                patch.object(stress_test.subprocess, 'Popen', side_effect=[SimpleNamespace(pid=1000+i) for i in range(50)]) as popen, \
                redirect_stdout(StringIO()):
            result = stress_test.launch(args)
        self.assertEqual(popen.call_count, 50)
        for key in ('port', 'output', 'log', 'pid'):
            self.assertEqual(len({job[key] for job in result['jobs']}), 50)
        for index, call in enumerate(popen.call_args_list):
            command = call.args[0]
            self.assertEqual(command[0], str(args.python))
            self.assertEqual(command[command.index('--port')+1], str(ports[index]))
            self.assertIn('--model-log', command)
            self.assertEqual(call.kwargs['env']['OPENAI_API_KEY'], 'test-secret')
            self.assertEqual(call.kwargs['env']['PORT'], str(ports[index]))
            self.assertTrue(call.kwargs['start_new_session'])
            self.assertEqual(call.kwargs['stdin'], stress_test.subprocess.DEVNULL)
        manifest = (args.output / 'manifest.json').read_text()
        self.assertNotIn('test-secret', manifest)
        self.assertEqual(json.loads(manifest), result)
        self.assertEqual(len(list((args.output / 'logs').glob('*.log'))), 50)

    def test_dry_run_does_not_start_processes_and_preserves_virtualenv_launcher(self):
        args = self.arguments('--dry-run')
        with patch.object(stress_test, 'available_ports', return_value=list(range(33000,33050))), \
                patch.object(stress_test.subprocess, 'Popen') as popen, redirect_stdout(StringIO()):
            result = stress_test.launch(args)
        popen.assert_not_called()
        self.assertEqual(len(result['jobs']), 50)
        self.assertTrue(all(job['pid'] is None for job in result['jobs']))
        self.assertEqual(result['jobs'][0]['command'][0], str(Path(stress_test.sys.executable).absolute()))

    def test_launch_failure_preserves_pids_of_jobs_already_started(self):
        args = self.arguments('--count', '2')
        with patch.object(stress_test, 'available_ports', return_value=[33000,33001]), \
                patch.object(stress_test.subprocess, 'Popen', side_effect=[SimpleNamespace(pid=1234), OSError('cannot launch')]), \
                redirect_stdout(StringIO()), self.assertRaisesRegex(OSError, 'cannot launch'):
            stress_test.launch(args)
        jobs = json.loads((args.output / 'manifest.json').read_text())['jobs']
        self.assertEqual(jobs[0]['pid'], 1234)
        self.assertEqual(jobs[0]['status'], 'launched')
        self.assertEqual(jobs[1]['status'], 'launch_failed')

    def test_occupied_port_is_skipped(self):
        probe = Mock()
        probe.bind.side_effect = [OSError(errno.EADDRINUSE, 'occupied'), None, None]
        with patch.object(stress_test.socket, 'socket') as socket:
            socket.return_value.__enter__.return_value = probe
            self.assertEqual(stress_test.available_ports(33000, 2), [33001, 33002])


if __name__ == '__main__':
    unittest.main()
