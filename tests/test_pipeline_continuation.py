"""All real passes reach a final report after one schema task exhausts retries."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from importlib import import_module
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.compiler import Compiler


class PipelineContinuation(unittest.TestCase):
    def test_real_passes_continue_after_a_design_failure_without_fabricating_obligations(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input'
            source.mkdir()
            (source / 'requirements.yaml').write_text(
                'id: ROOT\nchildren:\n  - id: BAD\n    name: Invalid proposal\n'
                '  - id: GOOD\n    name: Static module\n    description: No persistent data or pages.\n')
            compiler = Compiler(source, root / 'application')
            calls = []
            def schema_proposal(_, request):
                rid = request['requirement']['id']
                calls.append(rid)
                return {} if rid == 'BAD' else {'entities': {}, 'related_fields': []}
            with ExitStack() as stack, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                stack.enter_context(patch.object(import_module('02_build_db_schema'), 'TextModel',
                    return_value=Mock(generate_json=schema_proposal)))
                stack.enter_context(patch.object(import_module('03_infer_db_obligations'), 'TextModel',
                    return_value=Mock(generate_json=Mock(return_value={
                        'requirement': {'read': [], 'write': []}, 'steps': {}}))))
                stack.enter_context(patch.object(import_module('09_design_ui'), 'TextModel',
                    return_value=Mock(generate_json=Mock(return_value={
                        'pages': {}, 'elements': {}, 'bindings': {}, 'requirement_ui': [], 'step_ui': {}}))))
                stack.enter_context(patch.object(import_module('05_implement_db'), 'verify_database_runtime',
                    return_value={'status': 'GREEN'}))
                compiler.compile()
            self.assertEqual(calls, ['BAD'] * 10 + ['GOOD'])
            self.assertEqual(len(compiler.report['stages']), 13)
            self.assertEqual(compiler.report['status'], 'COMPLETED_WITH_FAILURES')
            self.assertEqual(compiler.report['stages']['09_design_ui']['status'], 'GREEN')
            self.assertIn('12_implement_frontend_tdd', compiler.report['stages'])
            obligations = json.loads((compiler.arc_dir / 'db_obligations.json').read_text())
            self.assertNotIn('BAD', obligations['requirements'])
            self.assertEqual(obligations['requirements']['GOOD'], {'read': [], 'write': []})
            self.assertIsNone(compiler.current_stage)
