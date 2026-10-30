"""Exercise in-process pass composition and the unified CLI without model requests."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from importlib import import_module
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import sys
from unittest.mock import patch

import main
import run_all
from infrastructure.compiler import Compiler
from infrastructure.utils.presentation.logging import session_info


PASSES = [
    ("00_project_initialization", "project_initialization"),
    ("01_explore_requirement", "explore_requirement"),
    ("02_build_db_schema", "build_db_schema"),
    ("03_infer_db_obligations", "infer_db_obligations"),
    ("04_check_db_obligations", "check_db_obligations"),
    ("05_implement_db", "implement_db"),
    ("06_decompose_backend_apis", "decompose_backend_apis"),
    ("07_infer_api_contracts", "infer_api_contracts"),
    ("08_implement_backend_tdd", "implement_backend_tdd"),
    ("09_design_ui", "design_frontend_ui"),
    ("10_implement_ui", "implement_frontend_ui"),
    ("11_design_ui_interactions", "design_ui_interactions"),
    ("12_implement_frontend_tdd", "implement_frontend_interactions"),
]


class CompilerPipeline(unittest.TestCase):
    def test_full_order_arguments_state_and_real_stage_log_context(self):
        calls = []
        original_argv = sys.argv[:]
        with TemporaryDirectory(prefix="compiler 中文 ") as temporary:
            root = Path(temporary)
            compiler = Compiler(root / "input", root / "application with spaces", model_log=True)

            def load(module):
                function = next(function for name, function in PASSES if name == module)
                def execute(*arguments):
                    session = session_info()
                    self.assertTrue(session['model_log'])
                    self.assertTrue(session['debug_model_io'])
                    self.assertTrue(session['stage'].startswith('Stage ' + module[:2]))
                    calls.append((module, arguments))
                    return {"pass": module}
                return SimpleNamespace(**{function: execute})

            with patch('infrastructure.compiler.import_module', side_effect=load), redirect_stdout(StringIO()):
                self.assertEqual(compiler.compile(), compiler.output_dir)
            self.assertEqual([name for name, _ in calls], [name for name, _ in PASSES])
            self.assertEqual(calls[0][1], (compiler.output_dir,))
            for module, arguments in calls[1:]:
                expected = (compiler.input_dir, compiler.arc_dir) if module[:2] in {'01', '09', '10', '11', '12'} else (compiler.arc_dir,)
                self.assertEqual(arguments, expected)
            self.assertEqual(compiler.artifacts['frontend_e2e']['pass'], '12_implement_frontend_tdd')
            self.assertIsNone(compiler.current_stage)
            self.assertIsNone(session_info())
            self.assertEqual(sys.argv, original_argv)
            log = (compiler.output_dir / 'compiler.log').read_text()
            self.assertIn('Stage 00', log)
            self.assertIn('Stage 12', log)

    def test_failure_stops_later_passes_and_preserves_completed_results(self):
        def load(module):
            if module == '00_project_initialization':
                return SimpleNamespace(project_initialization=lambda output: ['package.json'])
            raise ValueError('Invalid requirement JSON')
        with TemporaryDirectory() as temporary:
            compiler = Compiler(Path(temporary) / 'input', Path(temporary) / 'output')
            with patch('infrastructure.compiler.import_module', side_effect=load) as loader, redirect_stdout(StringIO()):
                with self.assertRaisesRegex(ValueError, 'Invalid requirement JSON'):
                    compiler.compile()
            self.assertEqual(loader.call_count, 2)
            self.assertEqual(compiler.current_stage, '01_explore_requirement.py')
            self.assertEqual(compiler.artifacts, {'project_files': ['package.json']})
            self.assertIsNone(session_info())

    def test_numbered_modules_expose_the_composed_pass_functions(self):
        for module, function in PASSES:
            self.assertTrue(callable(getattr(import_module(module), function)))

    def test_real_initialization_and_requirement_pass_compose_without_models(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'input'
            source.mkdir()
            (source / 'requirements.yaml').write_text('id: ROOT\nname: Empty application\nchildren: []\n')
            compiler = Compiler(source, root / 'output')
            with redirect_stdout(StringIO()):
                compiler._run('00_project_initialization', 'project_initialization', compiler.output_dir)
                result = compiler._run('01_explore_requirement', 'explore_requirement', source, compiler.arc_dir)
            self.assertEqual(result['id'], 'ROOT')
            self.assertTrue((compiler.output_dir / 'package.json').is_file())
            self.assertTrue((compiler.arc_dir / 'requirements.json').is_file())
            self.assertFalse((compiler.output_dir / 'model_calls.jsonl').exists())

    def test_all_real_passes_compose_for_a_no_operations_requirement(self):
        """Exercise artifact handoffs through all passes with no remote calls or npm installation."""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'input'
            source.mkdir()
            (source / 'requirements.yaml').write_text('id: ROOT\nname: Empty module\ndescription:\n  text: No business operations, data or pages.\nscenarios: []\nchildren: []\n')
            compiler = Compiler(source, root / 'application')
            proposals = {
                '02_build_db_schema': {'entities': {}, 'related_fields': []},
                '03_infer_db_obligations': {'requirement': {'read': [], 'write': []}, 'steps': {}},
                '06_decompose_backend_apis': {'apis': {}, 'requirement_apis': []},
                '07_infer_api_contracts': {},
                '09_design_ui': {'pages': {}, 'elements': {}, 'bindings': {}, 'requirement_ui': [], 'step_ui': {}},
            }
            with ExitStack() as stack, redirect_stdout(StringIO()):
                models = []
                for module, proposal in proposals.items():
                    model = stack.enter_context(patch.object(import_module(module), 'TextModel'))
                    model.return_value.generate_json.return_value = proposal
                    models.append(model)
                install = stack.enter_context(patch.object(import_module('08_implement_backend_tdd'), 'install_dependencies'))
                compiler.compile()
            install.assert_called_once_with(compiler.output_dir)
            self.assertEqual(sum(model.return_value.generate_json.call_count for model in models), 4)
            self.assertEqual(compiler.artifacts['backend_checks']['status'], 'NO_APIS')
            self.assertEqual(compiler.artifacts['frontend_e2e']['status'], 'NO_UI')
            for name in ('requirements', 'db_schema', 'db_obligations', 'backend_apis', 'backend_contracts',
                    'backend_tdd', 'ui_design', 'ui_checks', 'ui_interactions', 'frontend_e2e'):
                self.assertTrue((compiler.arc_dir / (name + '.json')).is_file(), name)
            self.assertIsNone(compiler.current_stage)


class CompilerCLI(unittest.TestCase):
    def source(self, root):
        source = root / 'input'
        source.mkdir()
        (source / 'requirements.yaml').write_text('id: ROOT\nchildren: []\n')
        return source

    def test_main_initializes_the_compiler_after_resolving_three_options(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root)
            output = root / 'output'
            with patch.object(main, 'Compiler') as cls:
                main.main(['--input', str(source), '--output', str(output), '--model-log'])
            cls.assert_called_once_with(source.resolve(), output.resolve(), model_log=True)
            cls.return_value.compile.assert_called_once_with()
            self.assertFalse(output.exists())
            args = main.parse_args(['--input', str(source), '--output', str(output)])
            self.assertFalse(args.model_log)
            self.assertTrue(main.parse_args(['--input', str(source), '--output', str(output), '--debug-model-io']).model_log)
            self.assertIs(run_all.main, main.main)

    def test_invalid_locations_fail_before_creating_compiler_or_output(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root)
            empty = root / 'empty'
            empty.mkdir()
            output_file = root / 'file'
            output_file.write_text('preserve')
            for inputs, output in [(root / 'missing', root / 'output'), (empty, root / 'output'),
                    (source, source), (source, source / 'nested'), (source, output_file)]:
                with self.subTest(inputs=inputs, output=output), patch.object(main, 'Compiler') as cls, redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        main.main(['--input', str(inputs), '--output', str(output)])
                    self.assertEqual(error.exception.code, 2)
                    cls.assert_not_called()
            self.assertFalse((root / 'output').exists())
            self.assertEqual(output_file.read_text(), 'preserve')

    def test_failure_and_interrupt_exit_without_starting_another_compilation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root)
            for failure, status in [(ValueError('failed test acceptance'), 1), (KeyboardInterrupt(), 130)]:
                with self.subTest(status=status), patch.object(main, 'Compiler') as cls, redirect_stderr(StringIO()):
                    cls.return_value.current_stage = '08_implement_backend_tdd.py'
                    cls.return_value.compile.side_effect = failure
                    with self.assertRaises(SystemExit) as error:
                        main.main(['--input', str(source), '--output', str(root / 'output')])
                    self.assertEqual(error.exception.code, status)
                    cls.return_value.compile.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
