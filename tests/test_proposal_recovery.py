"""Actual response-consumption errors return to the model without partial acceptance."""

from copy import deepcopy
import unittest
from unittest.mock import Mock

from infrastructure.shared.agent.proposals import propose_json


class ProposalRecovery(unittest.TestCase):
    def test_missing_keys_types_and_empty_records_can_repair_beyond_three_proposals(self):
        proposals = [{"read/write": {"read": []}}, {"read": None}, [], {"read": []},
            {"read": [7]}, {"read": ["note"]}]
        requests = []

        def generate(instructions, request):
            requests.append(deepcopy(request))
            return proposals[len(requests) - 1]

        request = {"task": "Read the first name"}
        result, accepted = propose_json(Mock(generate_json=generate), "Design", request,
            lambda value: value["read"][0].upper(), Mock(), "Example")
        self.assertEqual(result, "NOTE")
        self.assertEqual(accepted, proposals[-1])
        self.assertEqual(len(requests), 6)
        self.assertEqual([item["correction"]["error_type"] for item in requests[1:]],
            ["KeyError", "TypeError", "TypeError", "IndexError", "AttributeError"])
        for index, item in enumerate(requests[1:]):
            self.assertEqual(item["correction"]["previous_response"], proposals[index])
        self.assertNotIn("correction", request)

    def test_explicit_retry_limit_has_a_clear_failure_and_cause(self):
        model = Mock(generate_json=Mock(return_value={}))
        with self.assertRaisesRegex(RuntimeError, "Example exhausted 2 proposals") as failure:
            propose_json(model, "Design", {}, lambda value: value["read"], Mock(), "Example", 2)
        self.assertIsInstance(failure.exception.__cause__, KeyError)
        self.assertEqual(model.generate_json.call_count, 2)

    def test_interrupts_and_transport_failures_do_not_enter_response_repair(self):
        for failure in (KeyboardInterrupt(), RuntimeError("Model transport unavailable")):
            model = Mock(generate_json=Mock(side_effect=failure))
            with self.subTest(failure=type(failure).__name__), self.assertRaises(type(failure)):
                propose_json(model, "Design", {}, lambda value: value, Mock(), "Example")
            self.assertEqual(model.generate_json.call_count, 1)
