"""Shared file tools exercise real partial edits, adaptation and atomic failures."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.tools import FileTools, FileToolError, TOOL_REGISTRY, definition
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.utils.files import save_text


def call(tool, **arguments):
    return {"tool": tool, "arguments": arguments}


class FileToolTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_operations_run_sequentially_and_preserve_unrelated_content(self):
        path = "backend/src/example.ts"
        tools = SourceFiles(self.root, root="backend/src", tests_root="backend/tests").workspace()
        tools.execute([call("edit_file", path=path, operation="create", new_content="first\nmiddle\nlast\n"),
            call("edit_file", path=path, operation="replace", old_content="middle", new_content="updated"),
            call("edit_file", path=path, operation="prepend", new_content="// header\n"),
            call("edit_file", path=path, operation="append", new_content="// footer\n")])
        self.assertEqual((self.root / path).read_text(), "// header\nfirst\nupdated\nlast\n// footer\n")
        self.assertEqual(tools.last_changes, [{"path": path, "before": None,
            "after": "// header\nfirst\nupdated\nlast\n// footer\n"}])

    def test_exact_matching_errors_leave_entire_batch_unchanged(self):
        path, other = "backend/src/main.ts", "backend/src/other.ts"
        save_text(self.root / path, "same\nsame\nunique\n")
        tools = FileTools(self.root, [path, other])
        for old, code in (("missing", "OLD_CONTENT_NOT_FOUND"), ("same", "OLD_CONTENT_NOT_UNIQUE")):
            with self.subTest(code=code), self.assertRaises(FileToolError) as failed:
                tools.execute([call("edit_file", path=other, operation="create", new_content="new"),
                    call("edit_file", path=path, operation="replace", old_content=old, new_content="changed")])
            self.assertEqual(failed.exception.feedback["code"], code)
            self.assertFalse((self.root / other).exists())
            self.assertEqual((self.root / path).read_text(), "same\nsame\nunique\n")

    def test_creation_never_overwrites_existing_files_and_empty_files_allow_insertions(self):
        path = "backend/src/empty.ts"
        save_text(self.root / path, "")
        tools = FileTools(self.root, [path])
        with self.assertRaises(FileToolError) as failed:
            tools.execute([call("edit_file", path=path, operation="create", new_content="overwrite")])
        self.assertEqual(failed.exception.feedback["code"], "FILE_ALREADY_EXISTS")
        tools.execute([call("edit_file", path=path, operation="append", new_content="inserted")])
        self.assertEqual((self.root / path).read_text(), "inserted")

    def test_overlapping_old_content_is_ambiguous(self):
        path = "backend/src/repeated.ts"
        save_text(self.root / path, "aaa")
        tools = FileTools(self.root, [path])
        with self.assertRaises(FileToolError) as failed:
            tools.execute([call("edit_file", path=path, operation="replace", old_content="aa", new_content="b")])
        self.assertEqual(failed.exception.feedback["code"], "OLD_CONTENT_NOT_UNIQUE")

    def test_test_suffix_is_adapted_before_path_registration(self):
        tools = FileTools.for_target(self.root, "e2e_test", "REQ-A")
        results = tools.execute([call("edit_file", path="tests/save.ts", operation="create", new_content="test")])
        self.assertEqual(results[0]["result"]["path"], "frontend/tests/e2e/save.spec.ts")
        self.assertEqual(selected_path(self.root, "e2e_test", "REQ-A"), "frontend/tests/e2e/save.spec.ts")

    def test_target_directory_is_adapted_and_reported_before_retry(self):
        tools = FileTools.for_target(self.root, "backend_test", "API-A")
        requests = []
        def generate(_, payload):
            requests.append(payload)
            if len(requests) == 1:
                return {"tool_calls": [call("edit_file", path="tests/accounts/check.test.ts",
                    operation="create", new_content="first") ]}
            self.assertEqual(payload["task"]["test_path"], "backend/tests/accounts/check.test.ts")
            result = payload["context_result"]["tool_results"][0]["result"]
            self.assertEqual(result["requested_path"], "tests/accounts/check.test.ts")
            self.assertEqual(result["path"], "backend/tests/accounts/check.test.ts")
            return {"tool_calls": [call("edit_file", path=result["path"], operation="replace",
                old_content="first", new_content="repaired")]}
        run_file_agent(Mock(generate_json=generate), "Write the current API test", {}, tools,
            Mock(side_effect=[ValueError("Fix the test"), {"green": True}]), 2, Mock(), "test")
        self.assertEqual(selected_path(self.root, "backend_test", "API-A"), "backend/tests/accounts/check.test.ts")
        self.assertFalse((self.root / "tests/accounts/check.test.ts").exists())

    def test_fixed_sql_path_and_later_helper_creation_use_the_same_tool(self):
        path = "backend/src/db/tables/Note.sql"
        tools = FileTools.for_target(self.root, "db", "Note", fixed_path=path)
        results = tools.execute([call("edit_file", path="schema/note.sql", operation="create",
            new_content="CREATE TABLE Note(id INTEGER);")])
        self.assertEqual(results[0]["result"]["path"], path)
        self.assertEqual(tools.task_state({})["file_target"]["path"], path)
        with self.assertRaises(FileToolError):
            tools.execute([call("edit_file", path="backend/src/db/tables/Other.sql", operation="create", new_content="other")])

    def test_restricted_acceptance_cannot_read_application_sources(self):
        source, suite = "backend/src/business.ts", "frontend/tests/e2e/acceptance/current.spec.ts"
        save_text(self.root / source, "hidden implementation")
        tools = FileTools.for_target(self.root, "acceptance_test", "REQ-A", fixed_path=suite, readable=[suite])
        with self.assertRaises(FileToolError) as denied:
            tools.execute([call("read_file", path=source)])
        self.assertEqual(denied.exception.feedback["code"], "READ_NOT_ALLOWED")

    def test_write_failure_restores_bytes_and_does_not_register_a_target(self):
        original = b"\xef\xbb\xbfkeep\r\n"
        old = "backend/src/shared.ts"
        (self.root / old).parent.mkdir(parents=True)
        (self.root / old).write_bytes(original)
        tools = FileTools.for_target(self.root, "api", "API-A", writable=[old])
        def publish(path, content):
            if path.name == "created.ts":
                raise OSError("simulated failure")
            save_text(path, content)
        with patch("infrastructure.shared.agent.tools.save_text", side_effect=publish), self.assertRaises(OSError):
            tools.execute([call("edit_file", path=old, operation="replace", old_content="keep", new_content="changed"),
                call("edit_file", path="backend/src/created.ts", operation="create", new_content="new")])
        self.assertEqual((self.root / old).read_bytes(), original)
        self.assertIsNone(selected_path(self.root, "api", "API-A"))

    def test_registry_defines_the_model_schema_and_execution(self):
        tools = FileTools(self.root)
        schema = {item["function"]["name"]: item["function"] for item in tools.schemas()}
        self.assertEqual(set(schema), set(TOOL_REGISTRY))
        self.assertIn("operation", schema["edit_file"]["parameters"]["required"])
        self.assertNotIn(str(self.root), json.dumps(tools.schemas()))
        with self.assertRaises(FileToolError) as failed:
            tools.execute([call("unknown_file_tool", path="source.ts")])
        self.assertEqual(failed.exception.feedback["code"], "UNKNOWN_TOOL")

    def test_registered_read_tool_uses_the_shared_loop_without_a_new_dispatch_branch(self):
        entry = (lambda files: {"notice": "relevant evidence"},
            definition("inspect_context", "Read task evidence", {}, []), "read")
        model = Mock(generate_json=Mock(side_effect=[
            {"tool_calls": [call("inspect_context")]}, {"tool_calls": []}]))
        with patch.dict(TOOL_REGISTRY, {"inspect_context": entry}):
            run_file_agent(model, "Use the shared tools", {}, FileTools(self.root),
                Mock(return_value={"green": True}), 1, Mock(), "extension")
        payload = model.generate_json.call_args.args[1]
        self.assertEqual(payload["context_result"]["tool_results"][0]["result"], {"notice": "relevant evidence"})
