"""Shared identities survive later local tasks and remain selectively supplied."""
import unittest
from infrastructure.shared.agent.conventions import merge_conventions, select_conventions


class SharedConventions(unittest.TestCase):
    def test_session_decision_is_reused_across_registration_and_home(self):
        first = merge_conventions({}, {'conventions': {'session': 'Use HttpOnly sid cookie; resolve its account.'}},
            'REQ-HOME', ['Account.id', 'Session.token_hash'])
        second = merge_conventions(first, {}, 'REQ-REGISTER', ['Account.id', 'Session.token_hash'])
        self.assertEqual(select_conventions(second, requirements=['REQ-REGISTER']),
            {'session': 'Use HttpOnly sid cookie; resolve its account.'})
        self.assertEqual(first['session']['requirements'], ['REQ-HOME'])
        self.assertEqual(merge_conventions(second, {}, 'REQ-CATALOG', ['Product.id']), second)
        self.assertEqual(select_conventions(second, fields=['Product.id']), {})

    def test_explicit_correction_retains_identity_and_prior_consumers(self):
        original = merge_conventions({}, {'conventions': {'session': 'old'}}, 'REQ-A', ['Account.id'])
        revised = merge_conventions(original, {'conventions': {'session': 'new'}}, 'REQ-B', ['Account.id'])
        self.assertEqual(list(revised), ['session'])
        self.assertEqual(revised['session']['requirements'], ['REQ-A', 'REQ-B'])
        self.assertEqual(revised['session']['description'], 'new')
