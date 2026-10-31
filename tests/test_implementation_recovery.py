"""Failed tasks leave evidence, restore sources, and do not stop independent work."""

from contextlib import redirect_stdout
from importlib import import_module
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from infrastructure.compiler import Compiler
from infrastructure.shared.agent.files import FileWorkspace
from infrastructure.shared.agent.loop import AgentExhausted, run_file_agent
from infrastructure.shared.agent.recovery import implementation_task, final_checks
from infrastructure.shared.project.entrypoints import remember_path, selected_path
from infrastructure.shared.project.initialize import initialize_project
from infrastructure.stages.frontend.ui import implementation as ui_implementation
from infrastructure.utils.files import save_bytes, save_text


class ImplementationRecovery(unittest.TestCase):
    def test_exhaustion_archives_last_feedback_and_restores_sources_tests_and_index(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = b'original\r\n'
            save_bytes(root / 'backend/src/shared.ts', original)
            remember_path(root, 'api', 'ACCEPTED', 'backend/src/shared.ts')
            index = (root / '.arc/implementation_paths.json').read_bytes()
            workspace = FileWorkspace.for_target(root, 'api', 'FAILED', writable=['backend/src/shared.ts'])
            entry = {'status': 'IMPLEMENTING'}
            model = Mock()
            model.generate_json.side_effect = [
                {'edits': [{'path': 'backend/src/broken.ts', 'content': 'syntax error'},
                    {'path': 'backend/src/shared.ts', 'content': 'regression'}]},
                {'edits': [{'path': 'backend/src/broken.ts', 'content': 'still broken'}]}]
            gate = Mock(side_effect=ValueError('Real compiler failure'))
            with implementation_task(root, entry, Mock(), '08 / FAILED'):
                run_file_agent(model, 'Implement', {}, workspace, gate, 2, Mock(), 'FAILED')
            self.assertEqual(entry['status'], 'FAILED')
            self.assertEqual(entry['turns'], 2)
            self.assertEqual(entry['feedback'], [{'error': 'Real compiler failure'}])
            self.assertEqual((root / 'backend/src/shared.ts').read_bytes(), original)
            self.assertEqual((root / '.arc/implementation_paths.json').read_bytes(), index)
            self.assertFalse((root / 'backend/src/broken.ts').exists())
            self.assertIsNone(selected_path(root, 'api', 'FAILED'))
            archive = root / entry['archive']
            self.assertEqual((archive / 'files/backend/src/broken.ts').read_text(), 'still broken')
            self.assertEqual(json.loads((archive / 'failure.json').read_text())['feedback'], entry['feedback'])
            # A subsequent independent task still executes and commits its accepted edits.
            next_entry = {'status': 'IMPLEMENTING'}
            with implementation_task(root, next_entry, Mock(), '08 / NEXT'):
                save_text(root / 'backend/src/next.ts', 'accepted')
                next_entry['status'] = 'GREEN'
            self.assertEqual((root / 'backend/src/next.ts').read_text(), 'accepted')
            self.assertEqual(next_entry['status'], 'GREEN')

    def test_fatal_io_and_interrupts_are_not_suppressed(self):
        with TemporaryDirectory() as temporary:
            for error in (OSError('Disk unavailable'), KeyboardInterrupt(), KeyError('compiler defect')):
                with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                    with implementation_task(Path(temporary), {}, Mock(), 'task'):
                        raise error

    def test_final_tests_and_build_run_even_after_compilation_and_test_failure(self):
        compile_check = Mock(return_value={'returncode': 1, 'output': 'Compilation failed'})
        tests = Mock(return_value={'returncode': 0, 'tests': 0})
        build = Mock(return_value={'returncode': 0, 'output': 'Built'})
        from infrastructure.stages.backend.testing import require_green
        result = final_checks(Mock(), compile=(compile_check, None), tests=(tests, require_green), build=(build, None))
        self.assertEqual([value['status'] for value in result.values()], ['FAILED', 'FAILED', 'GREEN'])
        for action in (compile_check, tests, build):
            action.assert_called_once_with()

    def test_ui_exhaustion_restores_first_page_and_attempts_second_then_final_checks(self):
        from test_frontend_flow import frontend_fixture
        _, _, design, _, _, _ = frontend_fixture()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_project(root)
            calls = []
            def generate(instructions, payload):
                pid = payload['task']['page']['id']
                calls.append(pid)
                return {'edits': [{'path': f'frontend/src/pages/{pid}.tsx', 'content': pid}]}
            green = {'returncode': 0, 'passed': 1, 'failed': 0, 'output': 'passed'}
            red = {'returncode': 1, 'passed': 0, 'failed': 1, 'output': 'assertion failure',
                'errors': [], 'skipped': 0, 'flaky': 0, 'failures': ['Error: expect(locator).toBeVisible()']}
            checks = Mock()
            checks.typecheck.return_value = {'returncode': 0, 'output': 'compiled'}
            checks.tests.side_effect = lambda files: red if len(files) == 2 or 'editor' in files[0] or not (root / 'frontend/src/pages/summary.tsx').exists() else green
            checks.build.return_value = {'returncode': 0, 'output': 'built'}
            with patch.object(ui_implementation, 'install_dependencies'), patch.object(ui_implementation, 'FrontendChecks', return_value=checks):
                report = ui_implementation.implement_ui(root / '.arc', design, Mock(generate_json=generate), Mock(), {'pages': {}}, max_turns=1)
            self.assertEqual(calls, ['editor', 'summary'])
            self.assertEqual(report['status'], 'COMPLETED_WITH_FAILURES')
            self.assertEqual(report['pages']['editor']['status'], 'FAILED')
            self.assertEqual(report['pages']['summary']['status'], 'GREEN')
            self.assertFalse((root / 'frontend/src/pages/editor.tsx').exists())
            self.assertEqual(report['verification']['tests']['status'], 'FAILED')
            checks.build.assert_called_once_with()

    def test_partial_stage_reports_do_not_stop_later_compiler_passes(self):
        from test_compiler import PASSES
        calls = []
        def load(module):
            function = next(function for name, function in PASSES if name == module)
            def execute(*args, **kwargs):
                calls.append(module)
                return {'status': 'COMPLETED_WITH_FAILURES', 'failures': [{'task': 'API-A', 'status': 'FAILED'}]} if module.startswith('08') else {'status': 'GREEN'}
            return SimpleNamespace(**{function: execute})
        with TemporaryDirectory() as temporary:
            compiler = Compiler(Path(temporary) / 'input', Path(temporary) / 'output')
            with patch('infrastructure.compiler.import_module', side_effect=load), redirect_stdout(StringIO()):
                compiler.compile()
            self.assertEqual(calls, [name for name, _ in PASSES])
            report = json.loads((compiler.arc_dir / 'compilation.json').read_text())
            self.assertEqual(report['status'], 'COMPLETED_WITH_FAILURES')
            self.assertEqual(report['stages']['08_implement_backend_tdd']['failures'][0]['task'], 'API-A')
            self.assertEqual(report['stages']['12_implement_frontend_tdd']['status'], 'GREEN')
            # The public CLI signals failure only after it has attempted every pass.
            import main
            compiler.input_dir.mkdir()
            (compiler.input_dir / 'requirements.yaml').write_text('id: ROOT\nchildren: []\n')
            calls.clear()
            with patch('infrastructure.compiler.import_module', side_effect=load), patch.object(main, 'Compiler', return_value=compiler), redirect_stdout(StringIO()), patch('sys.stderr', new=StringIO()), self.assertRaises(SystemExit) as exit_status:
                main.main([str(compiler.input_dir), '-o', str(compiler.output_dir)])
            self.assertEqual(exit_status.exception.code, 1)
            self.assertEqual(calls, [name for name, _ in PASSES])

    def test_trigger_failure_restores_handlers_and_later_requirements_continue(self):
        from test_frontend_flow import frontend_fixture
        from infrastructure.stages.frontend.triggers import implementation
        _, tree, ui, design, backend, _ = frontend_fixture()
        for aid, api in backend['apis'].items():
            api['signature'] = {'method': 'POST', 'path': '/api/' + aid, 'name': aid}
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_project(root)
            calls = []
            green = {'returncode': 0, 'passed': 1, 'failed': 0, 'output': 'passed'}
            compiled = {'returncode': 0, 'output': 'compiled'}
            def run(model, instructions, task, files, gate, max_turns, console, label, **kwargs):
                rid = task['requirement']['id']
                calls.append((rid, 'implementation' if 'implementation_paths' in task else 'tests'))
                if 'implementation_paths' in task:
                    for path in task['implementation_paths'].values():
                        save_text(root / path, 'rejected' if rid == 'REQ-A' else 'accepted')
                    if rid == 'REQ-A':
                        raise AgentExhausted(label, 1, [{'error': 'Integration failure'}])
                    return {'turns': 1, 'checks': {'typecheck': compiled, 'e2e': green}}
                path = f'frontend/tests/e2e/{rid}.spec.ts'
                remember_path(root, 'e2e_test', rid, path)
                save_text(root / path, 'assertions')
                return {'turns': 1, 'checks': {'typecheck': compiled, 'behavior': green, 'status': 'GREEN'}}
            checks, api_checks = Mock(), Mock()
            checks.typecheck.return_value = compiled
            checks.tests.return_value = green
            checks.build.return_value = compiled
            api_checks.typecheck.return_value = compiled
            api_checks.tests.return_value = {'returncode': 0, 'tests': 0, 'pass': 0, 'fail': 0}
            with patch.object(implementation, 'install_dependencies'), patch.object(implementation, 'run_file_agent', side_effect=run), patch.object(implementation, 'E2EChecks', return_value=checks), patch.object(implementation, 'BackendChecks', return_value=api_checks):
                report = implementation.run_trigger_tdd(root / '.arc', tree, {'entities': {}}, backend,
                    ui, design, {}, {rid: {'id': rid} for rid in tree.leaves}, Mock(), Mock(), {'requirements': {}}, max_turns=1)
            self.assertEqual(report['status'], 'COMPLETED_WITH_FAILURES')
            self.assertEqual(report['requirements']['REQ-A']['status'], 'FAILED')
            self.assertEqual(report['requirements']['REQ-B']['status'], 'GREEN')
            self.assertEqual(report['requirements']['REQ-C']['status'], 'GREEN')
            self.assertIn(('REQ-B', 'implementation'), calls)
            self.assertFalse((root / 'frontend/tests/e2e/REQ-A.spec.ts').exists())
            archive = root / report['requirements']['REQ-A']['archive']
            self.assertTrue(list((archive / 'files/frontend/src/triggers').glob('*.ts')))
            checks.build.assert_called_once_with()

    def test_backend_test_generation_exhaustion_does_not_skip_later_apis(self):
        from test_backend_contracts import prepare_artifacts
        stage = import_module('08_implement_backend_tdd')
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            arc, _, contracts = prepare_artifacts(root)
            calls = []
            def run(model, instructions, task, files, gate, max_turns, console, label, **kwargs):
                calls.append(task['api_id'])
                raise AgentExhausted(label, max_turns, [{'error': 'Invalid test syntax'}])
            checks = Mock()
            checks.typecheck.return_value = {'returncode': 0, 'output': 'compiled'}
            checks.tests.return_value = {'returncode': 0, 'tests': 0, 'pass': 0, 'fail': 0}
            checks.build.return_value = {'returncode': 0, 'output': 'built'}
            from infrastructure.utils.files import save_json
            save_json(arc / 'backend_apis.json', contracts)
            with patch.object(stage, 'TextModel'), patch.object(stage, 'DemoConsole', return_value=Mock()), patch.object(stage, 'install_dependencies'), patch.object(stage, 'BackendChecks', return_value=checks), patch.object(stage, 'run_file_agent', side_effect=run):
                report = stage.implement_backend_tdd(arc, max_turns=1)
            self.assertEqual(set(calls), set(contracts['apis']))
            self.assertEqual(len(calls), len(set(calls)))
            self.assertEqual(report['status'], 'COMPLETED_WITH_FAILURES')
            self.assertEqual(len(report['failures']), len(contracts['apis']))
            checks.build.assert_called_once()


if __name__ == '__main__':
    unittest.main()
