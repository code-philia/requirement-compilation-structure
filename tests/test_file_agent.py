"""Regression checks for scoped file edits, repair feedback and fixed registrations."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from infrastructure.shared.agent.files import FileWorkspace
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.project.entrypoints import implementation_path, selected_path
from infrastructure.shared.project.initialize import initialize_project
from infrastructure.stages.backend.runtime import prepare_runtime, sync_implementations
from infrastructure.stages.frontend.ui.runtime import prepare_frontend, sync_pages
from infrastructure.stages.frontend.interactions.runtime import sync_interactions
from infrastructure.utils.files import read_source, save_text


class FileAgentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_scope_and_batch_validation_precede_all_writes(self):
        writable, reference = "src/current.ts", "src/frozen.ts"
        save_text(self.root / writable, "original")
        save_text(self.root / reference, "frozen")
        workspace = FileWorkspace(self.root, {writable}, [reference])
        workspace.state()
        for invalid in (reference, "src/unlisted.ts", "../escape.ts"):
            with self.subTest(path=invalid), self.assertRaises(ValueError):
                workspace.apply({"edits": [{"path": writable, "content": "changed"},
                    {"path": invalid, "content": "invalid"}]})
            self.assertEqual(read_source(self.root / writable), "original")
            self.assertEqual(read_source(self.root / reference), "frozen")
        workspace.apply({"edits": [{"path": writable, "content": "one"},
            {"path": writable, "content": "two", "explanation": "allowed metadata"}]})
        self.assertEqual(read_source(self.root / writable), "two")
        save_text(self.root / writable, "external change")
        with self.assertRaisesRegex(ValueError, "changed since"):
            workspace.apply({"edits": [{"path": writable, "content": "stale"}]})

    def test_symlink_parent_is_rejected(self):
        with TemporaryDirectory() as outside:
            try:
                (self.root / "linked").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Symlink creation is unavailable")
            with self.assertRaisesRegex(ValueError, "Symlink"):
                FileWorkspace(self.root, {"linked/source.ts"})

    def test_empty_edits_run_checks_and_failures_refresh_files(self):
        relative = "src/new.ts"
        workspace = FileWorkspace(self.root, {relative})
        model = Mock()
        model.generate_json.side_effect = [
            {"edits": []}, {"edits": [{"path": relative, "content": "bad"}]},
            {"edits": [{"path": relative, "content": "good"}]}]
        gate = Mock(side_effect=[ValueError("Missing implementation"), ValueError("Behavior failed"), {"green": True}])
        result = run_file_agent(model, "Implement the task", {"id": "example"}, workspace,
            gate, 3, Mock(), "example", feedback={"initial": "RED"})
        self.assertEqual(result, {"turns": 3, "checks": {"green": True}})
        requests = [call.args[1] for call in model.generate_json.call_args_list]
        self.assertEqual(set(requests[0]), {"task", "files", "feedback"})
        self.assertEqual(requests[0]["files"][relative], {"content": None, "writable": True})
        self.assertEqual(requests[2]["files"][relative]["content"], "bad")
        self.assertEqual(requests[2]["feedback"], [{"error": "Behavior failed"}])
        self.assertEqual(gate.call_count, 3)
        self.assertEqual(read_source(self.root / relative), "good")

    def test_fixed_paths_and_runtime_registration_need_no_index(self):
        initialize_project(self.root)
        api = {"API-EXAMPLE": {"signature": {"name": "example", "method": "GET", "path": "/api/example"}}}
        prepare_runtime(self.root, api)
        self.assertIn("status: 501", read_source(self.root / "backend/src/api/register.ts"))
        api_path = implementation_path("api", "API-EXAMPLE")
        page_path = implementation_path("page", "PAGE-EXAMPLE")
        event_path = implementation_path("event", "EVENT-EXAMPLE")
        save_text(self.root / api_path, "export async function handle() {}")
        save_text(self.root / page_path, "export function Page() {}")
        save_text(self.root / event_path, "export function handle() {}")
        sync_implementations(self.root, api)
        self.assertIn("handle as handler0", read_source(self.root / "backend/src/api/register.ts"))
        self.assertIn("handle as example", read_source(self.root / "backend/tests/support/apis.ts"))
        ui = {"pages": {"PAGE-EXAMPLE": {"route": "/", "root": "UI-ROOT"}}, "bindings": {}}
        prepare_frontend(self.root)
        sync_pages(self.root, ui)
        self.assertIn("Page as Page0", read_source(self.root / "frontend/src/App.tsx"))
        interactions = {"events": {"EVENT-EXAMPLE": {"write": [], "actions": []}}, "triggers": {}}
        sync_interactions(self.root, ui, interactions, {"apis": api}, [])
        self.assertNotIn("handle as event0", read_source(self.root / "frontend/src/ui-events.ts"))
        sync_interactions(self.root, ui, interactions, {"apis": api}, ["EVENT-EXAMPLE"])
        self.assertIn("handle as event0", read_source(self.root / "frontend/src/ui-events.ts"))
        self.assertFalse((self.root / ".arc/file_index.json").exists())
        names = [implementation_path("api", identity).casefold() for identity in ("API-A", "api-a", "API/A", "API:A", "CON", "中文")]
        self.assertEqual(len(set(names)), len(names))

    def test_model_selects_new_path_and_repairs_it_without_response_metadata(self):
        workspace = FileWorkspace.for_target(self.root, "api", "API-CREATE")
        model = Mock()
        relative = "backend/src/account/register-user.ts"
        model.generate_json.side_effect = [
            {"edits": [{"path": relative, "content": "first version"}]},
            {"edits": [{"path": relative, "content": "repaired version"}]},
        ]
        gate = Mock(side_effect=[ValueError("Behavior failed"), {"green": True}])
        result = run_file_agent(model, "Implement the API", {"api_id": "API-CREATE"}, workspace,
            gate, 2, Mock(), "Create API")
        requests = [call.args[1] for call in model.generate_json.call_args_list]
        self.assertEqual(requests[0]["files"], {})
        self.assertEqual(requests[0]["task"]["new_file"]["target"], "API-CREATE")
        self.assertNotIn("new_file", requests[1]["task"])
        self.assertTrue(requests[1]["files"][relative]["writable"])
        self.assertEqual(selected_path(self.root, "api", "API-CREATE"), relative)
        self.assertEqual(result["turns"], 2)
        resumed = FileWorkspace.for_target(self.root, "api", "API-CREATE")
        self.assertEqual(resumed.creation_task(), {})
        self.assertEqual(resumed.state()[relative]["content"], "repaired version")

    def test_retry_refreshes_target_path_hints_for_all_model_created_files(self):
        cases = [
            ("api", "API-CREATE", "backend/src/register.ts", {"implementation_path": None}, "implementation_path"),
            ("page", "PAGE-CREATE", "frontend/src/register.tsx", {"implementation_path": None}, "implementation_path"),
            ("backend_test", "API-CREATE", "backend/tests/register.test.ts", {"test_path": None}, "test_path"),
            ("e2e_test", "REQ-CREATE", "frontend/tests/e2e/register.spec.ts", {"test_path": None}, "test_path"),
            ("event", "EV-CREATE", "frontend/src/register-event.ts", {"implementation_paths": {"EV-CREATE": None}}, "implementation_paths"),
        ]
        for kind, identity, relative, task, key in cases:
            with self.subTest(kind=kind):
                workspace = FileWorkspace.for_target(self.root, kind, identity)
                model = Mock()
                model.generate_json.side_effect = [
                    {"edits": [{"path": relative, "content": "first version"}]},
                    {"edits": [{"path": relative, "content": "repaired version"}]},
                ]
                gate = Mock(side_effect=[ValueError("Acceptance failed"), {"green": True}])
                run_file_agent(model, "Implement target", task, workspace, gate, 2, Mock(), identity)
                first, retry = [call.args[1] for call in model.generate_json.call_args_list]
                self.assertIn("new_file", first["task"])
                self.assertNotIn("new_file", retry["task"])
                self.assertEqual(retry["task"][key], {identity: relative} if kind == "event" else relative)
                self.assertEqual(first["task"][key], {identity: None} if kind == "event" else None)
                self.assertEqual(task[key], {identity: None} if kind == "event" else None)
                self.assertEqual(retry["files"][relative], {"content": "first version", "writable": True})
                self.assertEqual(retry["feedback"], [{"error": "Acceptance failed"}])

    def test_empty_creation_response_requests_creation_without_running_gate(self):
        relative = "backend/src/created.ts"
        workspace = FileWorkspace.for_target(self.root, "api", "API-CREATE")
        model = Mock()
        model.generate_json.side_effect = [{"edits": []}, {"edits": [{"path": relative, "content": "created"}]}]
        gate = Mock(return_value={"green": True})
        run_file_agent(model, "Create target", {}, workspace, gate, 2, Mock(), "Create")
        gate.assert_called_once()
        retry = model.generate_json.call_args_list[1].args[1]
        self.assertIn("new_file", retry["task"])
        self.assertIn("Create the target file", retry["feedback"][0]["error"])

    def test_creation_rejects_overwrite_and_rolls_back_failed_registration(self):
        frozen = "backend/src/compiler.ts"
        save_text(self.root / frozen, "compiler-owned")
        workspace = FileWorkspace.for_target(self.root, "api", "API-CREATE", references=[frozen])
        workspace.state()
        for invalid in (frozen, "frontend/src/other.ts", "../escape.ts"):
            with self.subTest(path=invalid), self.assertRaises(ValueError):
                workspace.apply({"edits": [{"path": invalid, "content": "new"}]})
        from unittest.mock import patch
        with patch("infrastructure.shared.agent.files.remember_path", side_effect=OSError("Disk failure")):
            with self.assertRaisesRegex(OSError, "Disk failure"):
                workspace.apply({"edits": [{"path": "backend/src/new.ts", "content": "new"}]})
        self.assertFalse((self.root / "backend/src/new.ts").exists())
        self.assertEqual(read_source(self.root / frozen), "compiler-owned")
        self.assertIsNone(selected_path(self.root, "api", "API-CREATE"))

    def test_custom_paths_are_registered_for_backend_pages_and_events(self):
        initialize_project(self.root)
        api = {"API-CUSTOM": {"signature": {"name": "custom", "method": "GET", "path": "/api/custom"}}}
        prepare_runtime(self.root, api)
        paths = {"api": ("API-CUSTOM", "backend/src/features/account/read.ts", "export async function handle() {}"),
            "page": ("PAGE-CUSTOM", "frontend/src/screens/account.tsx", "export function Page() {}"),
            "event": ("EVENT-CUSTOM", "frontend/src/behavior/account/load.ts", "export function handle() {}")}
        for kind, (identity, path, content) in paths.items():
            workspace = FileWorkspace.for_target(self.root, kind, identity)
            workspace.state()
            workspace.apply({"edits": [{"path": path, "content": content}]})
        sync_implementations(self.root, api)
        self.assertIn("../features/account/read.js", read_source(self.root / "backend/src/api/register.ts"))
        ui = {"pages": {"PAGE-CUSTOM": {"route": "/", "root": "UI-ROOT"}}, "bindings": {}}
        prepare_frontend(self.root)
        sync_pages(self.root, ui)
        self.assertIn("./screens/account", read_source(self.root / "frontend/src/App.tsx"))
        interactions = {"events": {"EVENT-CUSTOM": {"write": [], "actions": []}}, "triggers": {}}
        sync_interactions(self.root, ui, interactions, {"apis": api}, ["EVENT-CUSTOM"])
        self.assertIn("./behavior/account/load", read_source(self.root / "frontend/src/ui-events.ts"))

    def test_new_test_file_paths_are_chosen_by_model(self):
        from infrastructure.stages.frontend.interactions.testing import test_path
        relative = "frontend/tests/e2e/accounts/register-flow.spec.ts"
        workspace = FileWorkspace.for_target(self.root, "e2e_test", "REQ-REGISTER")
        workspace.state()
        workspace.apply({"edits": [{"path": relative, "content": "test source"}]})
        self.assertEqual(test_path("REQ-REGISTER", self.root), relative)


if __name__ == "__main__":
    unittest.main()
