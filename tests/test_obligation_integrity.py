"""Missing declarations and unresolved symbols cannot become empty effects."""
import unittest
from copy import deepcopy
from infrastructure.stages.database.obligations.records import normalize_inference, check_symbols
from infrastructure.stages.frontend.triggers.design import validate_coverage
from infrastructure.stages.backend.primitives import ObligationCoverageError
from test_frontend_flow import frontend_fixture


class ObligationIntegrity(unittest.TestCase):
    def test_omitted_step_or_mode_differs_from_explicit_empty(self):
        value = {'requirement': {'read': [], 'write': []}, 'steps': {}}
        with self.assertRaises(KeyError):
            normalize_inference(value, ['S'])
        value['steps']['S'] = {'read': []}
        with self.assertRaises(KeyError):
            normalize_inference(value, ['S'])
        value['steps']['S']['write'] = []
        self.assertEqual(normalize_inference(value, ['S']), value)

    def test_unknown_field_is_rejected_even_if_not_related(self):
        schema = {'entities': {'Account': {'fields': {'id': {}}}}}
        check_symbols([{'read': ['Account.id'], 'write': []}], schema)
        with self.assertRaisesRegex(ValueError, 'Session.id'):
            check_symbols([{'read': ['Session.id'], 'write': []}], schema)

    def test_missing_frontend_call_or_step_is_rejected(self):
        _, tree, _, design, backend, obligations = frontend_fixture()
        obligations['steps'] = {sid: obligations['requirements'][rid]
            for rid in tree.leaves for sid in tree.own_steps[rid]}
        validate_coverage(design, backend, obligations, tree, tree.leaves)
        missing_call = deepcopy(design)
        missing_call['triggers']['TR-SAVE']['action'] = []
        with self.assertRaises(ObligationCoverageError):
            validate_coverage(missing_call, backend, obligations, tree, ['REQ-A'])
        missing_step = deepcopy(design)
        del missing_step['steps']['STEP-REQ-A']
        with self.assertRaises(KeyError):
            validate_coverage(missing_step, backend, obligations, tree, ['REQ-A'])
        # API possible effects include success writes, while rejection does not write.
        obligations['steps']['STEP-REQ-A'] = {'read': [], 'write': []}
        validate_coverage(design, backend, obligations, tree, ['REQ-A'])
