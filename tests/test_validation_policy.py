"""Only JSON structure and DB obligations gate model designs."""

from copy import deepcopy
import unittest

from infrastructure.stages.database.schema import validate_schema
from infrastructure.stages.database.validation import validate_response
from infrastructure.stages.backend.primitives import validate_design, ObligationCoverageError
from infrastructure.stages.backend.testing import require_green as backend_green
from infrastructure.stages.frontend.ui.testing import require_green as browser_green
from test_backend_contracts import object_schema


class ValidationPolicy(unittest.TestCase):
    def test_sql_and_schema_have_no_relational_policy_gate(self):
        schema = {"entities": {"Table": {"description": "", "fields": {
            "a": {"description": "", "type": "custom", "nullable": True, "primary_key": True,
                "unique": False, "references": "Missing.field", "constraints": []},
            "b": {"description": "", "type": "string", "nullable": True, "primary_key": True,
                "unique": False, "references": None, "constraints": []}}}}, "requirements": {}}
        validate_schema(schema)
        self.assertEqual(validate_response({"content": "arbitrary SQL", "path": "different"}, "fixed.sql"), "arbitrary SQL")
        with self.assertRaisesRegex(ValueError, "JSON shape"):
            validate_response({"content": []}, "fixed.sql")

    def test_api_gate_is_database_coverage_not_route_or_allocation_style(self):
        api = {"description": "", "read": ["Table.a"], "write": [],
            "signature": {"name": "same", "method": "CUSTOM", "path": "same"},
            "request": {}, "response": {"success": {"status": 900, "body": object_schema(), "headers": object_schema()}, "errors": []}}
        design = {"apis": {"A": api, "a": deepcopy(api)}, "requirements": {"REQ": ["A", "A"]}}
        obligations = {"requirements": {"REQ": {"read": ["Table.a"], "write": []}}}
        validate_design(design, obligations, {"Table.a"})
        design["apis"]["A"]["read"] = []
        with self.assertRaises(ObligationCoverageError): validate_design(design, obligations, {"Table.a"})
        design["apis"]["A"]["read"] = ["Unknown.field"]
        with self.assertRaisesRegex(ValueError, "Unknown schema symbols"): validate_design(design, obligations, {"Table.a"})

    def test_actual_test_failures_still_block_acceptance(self):
        backend_green({"returncode": 0, "tests": 1, "pass": 1, "fail": 0})
        browser_green({"returncode": 0, "passed": 1, "failed": 0})
        with self.assertRaises(ValueError): backend_green({"returncode": 1, "tests": 1, "pass": 0, "fail": 1})
        with self.assertRaises(ValueError): browser_green({"returncode": 1, "passed": 0, "failed": 1})


if __name__ == "__main__": unittest.main()
