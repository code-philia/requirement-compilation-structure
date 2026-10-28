"""Regression checks for scoped file edits, repair feedback and fixed registrations."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from infrastructure.shared.agent.files import FileWorkspace
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.project.entrypoints import implementation_path
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
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            workspace.apply({"edits": [{"path": writable, "content": "one"},
                {"path": writable, "content": "two"}]})
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


if __name__ == "__main__":
    unittest.main()
