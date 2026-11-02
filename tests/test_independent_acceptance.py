"""Independent tests cannot be rewritten by the application repair task."""
from tool_fixtures import propose_files
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import yaml

from infrastructure.shared.agent.context import SourceFiles
from infrastructure.stages.frontend.triggers.acceptance import run_independent_acceptance, acceptance_path
from test_frontend_flow import frontend_fixture


class IndependentAcceptance(unittest.TestCase):
    def setup_workspace(self, root):
        raw, tree, ui, triggers, backend, _ = frontend_fixture()
        input_dir = root / 'input'
        input_dir.mkdir()
        (input_dir / 'requirements.yaml').write_text(yaml.safe_dump(raw))
        return input_dir, ui, triggers, backend

    def test_real_behavior_failure_survives_separate_review_and_later_requirements_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir, ui, triggers, backend = self.setup_workspace(root)
            requests = []
            def generate(prompt, payload):
                requests.append(payload)
                task = payload['task']
                self.assertEqual([path for path, value in payload['files'].items() if value['writable']], [task['test_path']])
                self.assertNotIn('file', payload['context_kinds'])
                self.assertNotIn('triggers', task)
                if payload['feedback']:
                    return propose_files(root, [], diagnosis={'cause': 'implementation', 'reason': 'Required result is missing'})
                return propose_files(root, [{'path': task['test_path'], 'content': 'original requirement assertions'}])
            checks = Mock()
            checks.typecheck.return_value = {'returncode': 0}
            failure = {'returncode': 1, 'passed': 0, 'failed': 1, 'failures': ['wrong account']}
            green = {'returncode': 0, 'passed': 1, 'failed': 0}
            checks.tests.side_effect = [failure, failure, green, green]
            with patch('infrastructure.stages.frontend.triggers.acceptance.E2EChecks', return_value=checks):
                result = run_independent_acceptance(input_dir, root / '.arc', {'entities': {}}, backend, ui,
                    triggers, Mock(generate_json=generate), Mock())
            self.assertEqual(result['status'], 'COMPLETED_WITH_FAILURES')
            self.assertEqual(result['requirements']['REQ-A']['status'], 'FAILED')
            self.assertEqual(result['requirements']['REQ-C']['status'], 'GREEN')
            self.assertEqual((root / acceptance_path('REQ-A')).read_text(), 'original requirement assertions')
            self.assertEqual(len(requests), 4)

    def test_wrong_test_can_be_corrected_only_by_review_task_and_is_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir, ui, triggers, backend = self.setup_workspace(root)
            checks = Mock()
            checks.typecheck.return_value = {'returncode': 0}
            failure = {'returncode': 1, 'passed': 0, 'failed': 1, 'failures': ['invalid selector']}
            green = {'returncode': 0, 'passed': 1, 'failed': 0}
            checks.tests.side_effect = [failure, green, green, green]
            def generate(prompt, payload):
                corrected = bool(payload['feedback'])
                return propose_files(root, [{'path': payload['task']['test_path'], 'content': 'correct selector' if corrected else 'initial suite'}], diagnosis={'cause': 'test_overconstraint', 'reason': 'Selector contradicts original label'})
            with patch('infrastructure.stages.frontend.triggers.acceptance.E2EChecks', return_value=checks):
                report = run_independent_acceptance(input_dir, root / '.arc', {'entities': {}}, backend, ui,
                    triggers, Mock(generate_json=generate), Mock())
            self.assertEqual(report['status'], 'GREEN')
            path = acceptance_path('REQ-A')
            workspace = SourceFiles(root).workspace(references=[path])
            self.assertFalse(workspace.state()[path]['writable'])
            SourceFiles(root).include(workspace, [path])
            self.assertFalse(workspace.state()[path]['writable'])
            self.assertIn('test_overconstraint', (root / '.arc/test_repairs.jsonl').read_text())
            self.assertIn('initial suite', (root / '.arc/test_repairs.jsonl').read_text())
