"""Discovery is bounded, exact reads are current, and queries do not publish edits."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from infrastructure.shared.agent.discovery import ContextIndex, ContextLimit, check_budget
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.files import FileWorkspace


class ContextDiscovery(unittest.TestCase):
    def test_candidates_paging_and_exact_field_reads(self):
        entities = {f'Account{i}': {'description': 'session account', 'fields': {'id': {'type': 'integer'}}} for i in range(10)}
        index = ContextIndex(lambda: {'schema': entities})
        result = index.query({'kind': 'schema', 'query': 'session'})
        self.assertEqual(len(result['candidates']), 6)
        self.assertEqual(result['next_offset'], 6)
        self.assertNotIn('fields', result['candidates'][0])
        entities['Account0']['fields']['id']['type'] = 'uuid'
        self.assertEqual(index.query({'kind': 'schema', 'ids': ['Account0.id']})['records']['Account0.id']['type'], 'uuid')
        self.assertEqual(len(index.query({'kind': 'schema', 'query': 'session', 'offset': 6})['candidates']), 4)

    def test_queries_replace_results_without_consuming_proposal_attempts(self):
        requests = []
        def generate(_, request):
            from copy import deepcopy
            requests.append(deepcopy(request))
            return [{'context_request': {'kind': 'api', 'query': 'account'}},
                {'context_request': {'kind': 'api', 'ids': ['API-A']}}, {'apis': {}}][len(requests)-1]
        accept = Mock(return_value='accepted')
        result, _ = propose_json(Mock(generate_json=generate), '', {}, accept, Mock(), 'task', 1,
            ContextIndex({'api': {'API-A': {'description': 'account', 'request': {}}}}))
        self.assertEqual(result, 'accepted')
        accept.assert_called_once_with({'apis': {}})
        self.assertNotIn('candidates', requests[2]['context_result'])
        self.assertIn('API-A', requests[2]['context_result']['records'])

    def test_query_file_can_be_repaired_with_normal_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'frontend/src').mkdir(parents=True)
            path = 'frontend/src/helper.ts'
            (root / path).write_text('broken')
            model = Mock()
            model.generate_json.side_effect = [
                {'context_request': {'kind': 'file', 'ids': [path]}},
                {'edits': [{'path': path, 'content': 'fixed'}]}]
            gate = Mock(return_value={})
            run_file_agent(model, '', {}, FileWorkspace(root, []), gate, 1, Mock(), 'test')
            self.assertEqual((root / path).read_text(), 'fixed')
            gate.assert_called_once()

    def test_budget_is_explicit_and_never_truncates(self):
        with patch.dict('os.environ', {'ARC_CONTEXT_MAX_CHARS': '20'}):
            with self.assertRaisesRegex(ContextLimit, 'No evidence was truncated'):
                check_budget({'requirement': 'x' * 40})
