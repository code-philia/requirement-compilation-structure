"""API obligation coverage is the only additional design acceptance gate."""

from copy import deepcopy
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.stages.backend.primitives import validate_design, ObligationCoverageError
from infrastructure.stages.database.obligations.records import normalize_inference
from infrastructure.stages.backend.testing import require_green as backend_green
from infrastructure.stages.frontend.ui.testing import require_green as browser_green


class ValidationPolicy(unittest.TestCase):
    def test_api_coverage_uses_only_read_write_sets(self):
        api = {"read": ["Table.a"], "write": [], "signature": "arbitrary metadata"}
        design = {"apis": {"A": api, "a": deepcopy(api)}, "requirements": {"REQ": ["A", "A"]}}
        obligations = {"requirements": {"REQ": {"read": ["Table.a"], "write": []}}}
        validate_design(design, obligations)
        design["apis"]["A"]["read"] = []
        with self.assertRaises(ObligationCoverageError): validate_design(design, obligations)
        design["apis"]["A"].update(read=[], write=["Table.a"])
        with self.assertRaises(ObligationCoverageError): validate_design(design, obligations)

    def test_obligation_inference_has_no_symbol_or_related_field_gate(self):
        result = normalize_inference({"requirement": {"read": ["Unknown.field"], "write": []}}, [])
        self.assertEqual(result["requirement"]["read"], ["Unknown.field"])

    def test_stage03_does_not_require_all_related_fields_to_be_classified(self):
        from test_backend_contracts import prepare_artifacts
        stage = import_module("03_infer_db_obligations")
        proposal = {"requirement": {"read": [], "write": []}, "steps": {}}
        with TemporaryDirectory() as temporary:
            arc, _, _ = prepare_artifacts(Path(temporary))
            with patch.object(stage, "TextModel", return_value=Mock(generate_json=Mock(return_value=proposal))), \
                    patch.object(stage, "DemoConsole", return_value=Mock()):
                result = stage.infer_db_obligations(arc)
        self.assertEqual(result["requirements"]["REQ-A"], {"read": [], "write": []})

    def test_actual_test_failures_still_block_acceptance(self):
        backend_green({"returncode": 0, "tests": 1, "pass": 1, "fail": 0})
        browser_green({"returncode": 0, "passed": 1, "failed": 0})
        with self.assertRaises(ValueError): backend_green({"returncode": 1, "tests": 1, "pass": 0, "fail": 1})
        with self.assertRaises(ValueError): browser_green({"returncode": 1, "passed": 0, "failed": 1})
