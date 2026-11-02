"""Sequential schema updates define every field before requirement associations use it."""

from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.stages.database.schema import apply_patch, check_related_fields
from infrastructure.utils.files import save_json


def field(description):
    return {'description': description, 'type': 'string', 'nullable': False,
        'primary_key': False, 'unique': False, 'references': None, 'constraints': []}


class SchemaEvolution(unittest.TestCase):
    def proposals(self):
        bad = {'entities': {'Account': {'description': 'Accounts', 'fields': {'id': field('Account ID')}}},
            'related_fields': ['Account.id', 'Session.id', 'Session.account_id']}
        fixed = deepcopy(bad)
        fixed['entities']['Session'] = {'description': 'Persistent sessions',
            'fields': {'id': field('Session ID'), 'account_id': field('Session owner')}}
        return bad, fixed

    def test_new_and_existing_fields_resolve_after_merge_without_changing_baseline(self):
        _, fixed = self.proposals()
        baseline = {'entities': {}, 'requirements': {}}
        updated = apply_patch(baseline, fixed)
        check_related_fields(updated, fixed['related_fields'])
        self.assertEqual(baseline, {'entities': {}, 'requirements': {}})
        patch_record = {'entities': {'Session': {'fields': {'token': field('Credential hash')}}},
            'related_fields': ['Account.id', 'Session.id', 'Session.token']}
        extended = apply_patch(updated, patch_record)
        check_related_fields(extended, patch_record['related_fields'])
        self.assertEqual(extended['entities']['Session']['fields']['id'], field('Session ID'))
        self.assertNotIn('token', updated['entities']['Session']['fields'])

    def test_undefined_entity_field_and_synonym_are_rejected_with_repair_instructions(self):
        bad, fixed = self.proposals()
        with self.assertRaisesRegex(ValueError, 'Session.account_id, Session.id'):
            check_related_fields(apply_patch({'entities': {}}, bad), bad['related_fields'])
        updated = apply_patch({'entities': {}}, fixed)
        for missing in ['Session.token', 'AccountSession.id']:
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, missing):
                check_related_fields(updated, [missing])

    def test_bad_stage02_proposal_is_repaired_before_next_requirement_and_stage03(self):
        stage2 = import_module('02_build_db_schema')
        stage3 = import_module('03_infer_db_obligations')
        bad, fixed = self.proposals()
        with TemporaryDirectory() as temporary:
            arc = Path(temporary)
            save_json(arc / 'requirements.json', {'id': 'ROOT', 'children': [
                {'id': 'REQ-1', 'name': 'Restore current user', 'description': 'Read the existing session.'},
                {'id': 'REQ-2', 'name': 'Register', 'description': 'Create an account and session.'}]})
            requests = []
            def generate(instructions, request):
                requests.append(deepcopy(request))
                if len(requests) == 1:
                    return bad
                if len(requests) == 2:
                    self.assertEqual(json.loads((arc / 'db_schema.json').read_text())['entities'], {})
                    self.assertEqual(request['symbol_inventory'], {})
                    self.assertIn('Session.id', request['correction']['error'])
                    self.assertEqual(request['correction']['previous_response'], bad)
                    return fixed
                self.assertEqual(request['requirement']['id'], 'REQ-2')
                self.assertEqual(set(request['symbol_inventory']), {'Account', 'Session'})
                return {'entities': {}, 'related_fields': ['Account.id', 'Session.id']}
            with patch.object(stage2, 'TextModel', return_value=Mock(generate_json=generate)), patch.object(stage2, 'DemoConsole', return_value=Mock()):
                schema = stage2.build_db_schema(arc, max_attempts=2)
            self.assertEqual(len(requests), 3)
            self.assertEqual(schema['requirements']['REQ-1'], sorted(fixed['related_fields']))
            self.assertEqual(json.loads((arc / 'db_schema.json').read_text()), schema)
            inference = Mock(generate_json=Mock(return_value={'requirement': {'read': ['Session.id'], 'write': []}, 'steps': {}}))
            with patch.object(stage3, 'TextModel', return_value=inference), patch.object(stage3, 'DemoConsole', return_value=Mock()):
                result = stage3.infer_db_obligations(arc)
            self.assertEqual(inference.generate_json.call_count, 2)
            self.assertEqual(result['requirements']['REQ-1']['read'], ['Session.id'])

    def test_legacy_invalid_artifact_has_clear_error_before_model_request(self):
        stage3 = import_module('03_infer_db_obligations')
        with TemporaryDirectory() as temporary:
            arc = Path(temporary)
            save_json(arc / 'requirements.json', {'id': 'ROOT', 'children': [{'id': 'REQ-1', 'name': 'Home'}]})
            save_json(arc / 'db_schema.json', {'entities': {}, 'requirements': {'REQ-1': ['Session.id']}})
            model = Mock()
            with patch.object(stage3, 'TextModel', return_value=model), patch.object(stage3, 'DemoConsole', return_value=Mock()), self.assertRaises(RuntimeError) as failure:
                stage3.infer_db_obligations(arc)
            self.assertIn('Rerun 02_build_db_schema.py', failure.exception.failures[0]['error'])
            self.assertEqual(failure.exception.failures[0]['task'], 'REQ-1')
            model.generate_json.assert_not_called()


if __name__ == '__main__':
    unittest.main()
