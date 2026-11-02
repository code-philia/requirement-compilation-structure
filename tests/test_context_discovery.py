"""Discovery is bounded, exact reads are current, and queries do not publish edits."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from infrastructure.shared.agent.discovery import ContextIndex, DiscoverySession, DiscoveryStalled
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

    def test_large_input_and_more_than_six_ids_have_no_artificial_cap(self):
        records = {f'Entity{i}': {'description': 'x' * 30000, 'fields': {}} for i in range(8)}
        with patch.dict('os.environ', {'ARC_CONTEXT_MAX_CHARS': '20'}):
            result = ContextIndex({'schema': records}).query({'kind': 'schema', 'ids': list(records)})
        self.assertEqual(len(result['records']), 8)
        self.assertEqual(result['records']['Entity0']['description'], 'x' * 30000)

    def test_more_than_four_useful_queries_can_finish_one_proposal(self):
        responses = [{'context_request': {'kind': 'schema', 'ids': [f'Entity{i}']}} for i in range(8)]
        responses.append({'entities': {}})
        records = {f'Entity{i}': {'fields': {}} for i in range(8)}
        model = Mock(generate_json=Mock(side_effect=responses))
        accepted, _ = propose_json(model, '', {'requirement': 'x' * 190000}, lambda result: result,
            Mock(), 'schema', 1, ContextIndex({'schema': records}))
        self.assertEqual(accepted, {'entities': {}})
        self.assertEqual(model.generate_json.call_count, 9)

    def test_repeated_search_returns_guidance_then_can_repair_with_a_proposal(self):
        model = Mock(generate_json=Mock(side_effect=[
            *[{'context_request': {'kind': 'schema', 'query': 'account'}} for _ in range(3)],
            {'entities': {}}]))
        result, _ = propose_json(model, '', {}, lambda value: value['entities'], Mock(), 'schema', 2,
            ContextIndex({'schema': {'Account': {'description': 'account', 'fields': {}}}}))
        self.assertEqual(result, {})
        payload = model.generate_json.call_args.args[1]
        self.assertIn('same evidence', payload['correction']['error'])

    def test_malformed_query_returns_feedback_then_can_finish(self):
        model = Mock(generate_json=Mock(side_effect=[{'context_request': {'kind': 'absent'}}, {'entities': {}}]))
        result, _ = propose_json(model, '', {}, lambda value: value, Mock(), 'schema', 1, ContextIndex({'schema': {}}))
        self.assertEqual(result, {'entities': {}})
        self.assertIn('error', model.generate_json.call_args.args[1]['context_result'])

    def test_file_agent_can_read_more_than_four_dependencies_before_editing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'frontend/src').mkdir(parents=True)
            paths = [f'frontend/src/helper{i}.ts' for i in range(7)]
            for number, path in enumerate(paths):
                (root / path).write_text(f'export const value{number} = {number};')
            responses = [{'context_request': {'kind': 'file', 'ids': [path]}} for path in paths]
            responses.append({'edits': [{'path': paths[-1], 'content': 'fixed'}]})
            model = Mock(generate_json=Mock(side_effect=responses))
            result = run_file_agent(model, '', {'requirement': 'x' * 190000}, FileWorkspace(root, []),
                Mock(return_value={}), 1, Mock(), 'current task')
            self.assertEqual(result['turns'], 1)
            self.assertEqual((root / paths[-1]).read_text(), 'fixed')
            self.assertEqual(model.generate_json.call_count, 8)
