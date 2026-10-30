"""Complete API design, shared requirement context and obligation coverage."""

from copy import deepcopy
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import json
from unittest.mock import Mock, patch

from infrastructure.shared.project.initialize import initialize_project
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


class BackendDesign(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        self.arc, self.schema, self.design = prepare_artifacts(self.output)
        self.stage = import_module("06_design_backend_apis")

    def proposal(self, rid):
        ids = self.design["requirements"][rid]
        return {"apis": {aid: {**deepcopy(self.design["apis"][aid]), **conditions(aid)} for aid in ids},
            "requirement_apis": ids}

    def run_design(self, generate):
        with patch.object(self.stage, "TextModel", return_value=Mock(generate_json=generate)), \
                patch.object(self.stage, "DemoConsole", return_value=Mock()):
            return self.stage.design_backend_apis(self.arc)

    def test_complete_api_and_shared_updates_are_designed_in_one_call_per_requirement(self):
        requests = []
        def generate(instructions, payload):
            requests.append(deepcopy(payload))
            proposal = self.proposal(payload["requirement"]["id"])
            if payload["requirement"]["id"] == "REQ-B":
                proposal["apis"]["API-SAVE"]["request"]["body"]["description"] = "Shared note input"
                proposal["apis"]["API-SAVE"]["postcondition"][0]["description"] = "Save notes for both requirements"
            return proposal
        result = self.run_design(generate)
        self.assertEqual(len(requests), 3)
        self.assertEqual([call["requirement"]["id"] for call in requests], ["REQ-A", "REQ-B", "REQ-C"])
        shared = requests[1]
        self.assertEqual([use["id"] for use in shared["api_uses"]["API-SAVE"]], ["REQ-A"])
        self.assertEqual(shared["api_uses"]["API-SAVE"][0]["steps"][0]["id"], "STEP-REQ-A")
        self.assertEqual(shared["requirement"]["steps"][0]["id"], "STEP-REQ-B")
        self.assertIn("postcondition", shared["retrieved_apis"]["API-SAVE"])
        self.assertEqual(result["requirements"]["REQ-A"], result["requirements"]["REQ-B"])
        self.assertEqual(result["apis"]["API-SAVE"]["request"]["body"]["description"], "Shared note input")
        self.assertEqual(result["apis"]["API-SAVE"]["postcondition"][0]["description"], "Save notes for both requirements")
        self.assertEqual(json.loads((self.arc / "backend_apis.json").read_text()), result)
        for api in result["apis"].values():
            self.assertTrue({"signature", "request", "response", "read", "write", "precondition", "postcondition"} <= set(api))

    def test_shared_api_updates_recheck_previous_requirement_coverage(self):
        requests = []
        def generate(instructions, payload):
            requests.append(deepcopy(payload))
            rid = payload["requirement"]["id"]
            proposal = self.proposal(rid)
            if rid == "REQ-B" and "correction" not in payload:
                writer = proposal["apis"]["API-SAVE"]
                proposal["apis"]["API-OTHER"] = deepcopy(writer)
                writer["write"] = []
                proposal["requirement_apis"] = ["API-OTHER"]
            return proposal
        result = self.run_design(generate)
        self.assertEqual(len(requests), 4)
        feedback = requests[2]["correction"]["obligation_coverage"]
        self.assertEqual(feedback["requirement_id"], "REQ-A")
        self.assertEqual(feedback["missing"]["write"], ["Note.id", "Note.text"])
        self.assertNotIn("API-OTHER", requests[2]["api_inventory"])
        self.assertNotIn("API-OTHER", result["apis"])

    def test_complete_api_design_has_no_pq_semantic_gate(self):
        def generate(instructions, payload):
            proposal = self.proposal(payload["requirement"]["id"])
            for api in proposal["apis"].values():
                api["precondition"] = []
                api["postcondition"] = []
            return proposal
        result = self.run_design(generate)
        self.assertEqual(result["apis"]["API-SAVE"]["postcondition"], [])

    def test_invalid_json_is_retried_with_the_original_response(self):
        requests = []
        def generate(instructions, payload):
            requests.append(deepcopy(payload))
            if len(requests) == 1:
                raise json.JSONDecodeError("Invalid JSON", "{broken", 1)
            return self.proposal(payload["requirement"]["id"])
        self.run_design(generate)
        self.assertEqual(len(requests), 4)
        self.assertEqual(requests[1]["correction"]["invalid_response"], "{broken")


if __name__ == "__main__":
    unittest.main()
