"""P/Q semantics, shared API context and simplified backend TDD regressions."""

from copy import deepcopy
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.project.initialize import initialize_project
from infrastructure.stages.backend.contracts import CONTRACT_KEYS, validate_contract, validate_contracts
from infrastructure.stages.backend.testing import condition_tokens, validate_test_source
from infrastructure.utils.files import save_json, save_text


def object_schema(properties=None):
    return {"type": "object", "properties": properties or {}}


def prepare_artifacts(output):
    """Build real stage inputs with a shared writer API and an independent reader API."""
    initialize_project(output)
    requirements = {"id": "ROOT", "children": [
        {"id": rid, "name": rid, "description": "Save a note" if rid != "REQ-C" else "Count notes",
         "scenarios": [{"id": "SCN-" + rid, "steps": [{"id": "STEP-" + rid, "Given": "Existing notes", "When": "Use this API", "Then": "Observe its result"}]}]}
        for rid in ("REQ-A", "REQ-B", "REQ-C")]}
    fields = {name: {"description": name, "type": kind, "nullable": False, "primary_key": name == "id",
        "unique": False, "references": None, "constraints": []} for name, kind in (("id", "integer"), ("text", "string"))}
    symbols = ["Note.id", "Note.text"]
    schema = {"entities": {"Note": {"description": "Persisted notes", "fields": fields}},
        "requirements": {rid: ([] if rid == "ROOT" else symbols) for rid in ("ROOT", "REQ-A", "REQ-B", "REQ-C")}}
    records = {rid: {"read": symbols if rid == "REQ-C" else [], "write": symbols if rid in {"REQ-A", "REQ-B"} else []}
        for rid in schema["requirements"]}
    obligations = {"requirements": records, "steps": {"STEP-" + rid: records[rid] for rid in ("REQ-A", "REQ-B", "REQ-C")}}
    writer = {"description": "Save a nonempty note, rejecting empty text without writes", "read": [], "write": symbols,
        "signature": {"name": "saveNote", "method": "POST", "path": "/api/notes"},
        "request": {key: object_schema() for key in ("params", "query", "body", "headers")},
        "response": {"success": {"status": 200, "body": object_schema({"saved": {"type": "boolean"}}), "headers": object_schema()},
            "errors": [{"status": 400, "body": object_schema({"error": {"type": "string"}}), "headers": object_schema()}]}}
    writer["request"]["body"] = {**object_schema({"text": {"type": "string", "minLength": 1}}), "required": ["text"]}
    reader = {"description": "Count existing notes without writes", "read": symbols, "write": [],
        "signature": {"name": "countNotes", "method": "GET", "path": "/api/notes/count"},
        "request": {key: object_schema() for key in ("params", "query", "body", "headers")},
        "response": {"success": {"status": 200, "body": object_schema({"count": {"type": "integer"}}), "headers": object_schema()}, "errors": []}}
    design = {"apis": {"API-SAVE": writer, "API-COUNT": reader},
        "requirements": {"ROOT": [], "REQ-A": ["API-SAVE"], "REQ-B": ["API-SAVE"], "REQ-C": ["API-COUNT"]}}
    arc = output / ".arc"
    for name, value in (("requirements.json", requirements), ("db_schema.json", schema),
            ("db_obligations.json", obligations), ("backend_apis.json", design)):
        save_json(arc / name, value)
    save_text(output / "backend/src/db/tables/Note.sql", "CREATE TABLE IF NOT EXISTS Note (id INTEGER PRIMARY KEY, text TEXT NOT NULL);\n")
    path = output / "backend/src/db/initialize.ts"
    save_text(path, path.read_text().replace("tableFiles: readonly string[] = []", 'tableFiles: readonly string[] = ["Note.sql"]'))
    return arc, schema, design


def conditions(aid):
    if aid == "API-COUNT":
        return {"precondition": [], "postcondition": [{"id": "Q-1", "description": "Return the number of notes without changing records", "status": 200}]}
    return {"precondition": [{"id": "P-1", "description": "Text must be nonempty", "error_status": 400}],
        "postcondition": [{"id": "Q-1", "description": "Save one note and return saved=true", "status": 200},
            {"id": "Q-2", "description": "Reject empty text without inserting a note", "status": 400}]}


class BackendContracts(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        self.arc, self.schema, self.design = prepare_artifacts(self.output)
        self.api = {**self.design["apis"]["API-SAVE"], **conditions("API-SAVE")}

    def validate(self, api):
        validate_contract({key: api[key] for key in CONTRACT_KEYS})

    def test_semantic_conditions_keep_status_and_identity_checks(self):
        self.validate(self.api)
        for change in ("unknown_status", "success_as_rejection", "missing_q", "duplicate_id", "blank_description", "legacy_pointer"):
            api = deepcopy(self.api)
            if change == "unknown_status": api["postcondition"][0]["status"] = 201
            elif change == "success_as_rejection": api["precondition"][0]["error_status"] = 200
            elif change == "missing_q": api["postcondition"].pop()
            elif change == "duplicate_id": api["postcondition"][1]["id"] = "Q-1"
            elif change == "blank_description": api["precondition"][0]["description"] = " "
            else: api["precondition"][0]["request_fields"] = ["/body/text"]
            with self.subTest(change=change), self.assertRaises(ValueError): self.validate(api)
        reader = {**self.design["apis"]["API-COUNT"], **conditions("API-COUNT")}
        self.validate(reader)

    def test_test_titles_require_conditions_without_field_labels(self):
        source = 'import { test } from "node:test"; import assert from "node:assert/strict";\ntest("P-1 Q-1 Q-2 saves valid text and rejects empty text", async () => { assert.equal(1, 1); });'
        self.assertEqual(condition_tokens(self.api), {"P-1", "Q-1", "Q-2"})
        validate_test_source(source, self.api, 1)
        with self.assertRaisesRegex(ValueError, "Q-2"):
            validate_test_source(source.replace("Q-2", ""), self.api, 1)
        with self.assertRaisesRegex(ValueError, "at most 1"):
            validate_test_source(source + '\ntest("another case", () => { assert.ok(true); });', self.api, 1)

    def test_inference_uses_all_owners_and_preserves_interfaces(self):
        stage = import_module("07_infer_api_contracts")
        requests = []
        def generate(instructions, payload):
            requests.append(deepcopy(payload))
            return {"contract": conditions(payload["api_id"])}
        model = Mock(generate_json=Mock(side_effect=generate))
        with patch.object(stage, "TextModel", return_value=model), patch.object(stage, "DemoConsole", return_value=Mock()):
            result = stage.infer_api_contracts(self.arc)
        self.assertEqual(len(requests), 2)
        self.assertEqual([use["id"] for use in requests[0]["all_requirement_uses"]], ["REQ-A", "REQ-B"])
        self.assertNotIn("concatenated_steps", requests[0]["all_requirement_uses"][0])
        self.assertEqual(requests[1]["existing_contracts"], {"API-SAVE": result["apis"]["API-SAVE"]})
        validate_contracts(result, self.design)



if __name__ == "__main__":
    unittest.main()
