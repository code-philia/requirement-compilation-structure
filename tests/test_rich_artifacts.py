"""Presentation stays read-only and preserves real compiler relationships."""

from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import unittest

from rich.console import Console

from infrastructure.utils.presentation.artifacts import render_artifact
from infrastructure.utils.presentation.console import DemoConsole


class RichArtifacts(unittest.TestCase):
    def render(self, kind, data, previous=None, context=None):
        stream = StringIO()
        Console(file=stream, width=110, color_system=None).print(render_artifact(kind, data, previous, context))
        return stream.getvalue()

    def test_schema_diff_preserves_input_and_reports_removed_fields(self):
        before = {"entities": {"Session": {"fields": {"old": {"type": "string"}}}}}
        after = {"entities": {"Session": {"fields": {"active": {"type": "boolean", "nullable": False}}}}}
        copy = deepcopy(after)
        result = self.render("db_schema", after, before)
        self.assertIn("1 added", result)
        self.assertIn("1 removed", result)
        self.assertIn("Session.active", result)
        self.assertIn("Session.old", result)
        self.assertEqual(after, copy)

    def test_trigger_api_database_chain_uses_declared_relationships(self):
        design = {"triggers": {"logout": {"source": "logout-button", "event": "click", "action": [{"kind": "api", "api": "logoutApi"}]}},
            "requirements": {"REQ-4": ["logout"]}}
        backend = {"backend_apis": {"apis": {"logoutApi": {"read": ["Session.id"], "write": ["Session.active"]}}}}
        result = self.render("frontend_triggers", design, context=backend)
        for label in ("REQ-4", "logout-button", "click", "logoutApi", "Session.id", "Session.active"):
            self.assertIn(label, result)
        self.assertNotIn("Account.password", result)

    def test_ui_cycles_and_unresolved_parents_cannot_hang_visualization(self):
        design = {"pages": {"home": {"root": "a", "route": "/"}}, "elements": {
            "a": {"type": "container", "parent": "b"}, "b": {"type": "container", "parent": "a"},
            "orphan": {"parent": "missing"}}}
        result = self.render("ui_design", design)
        self.assertIn("home", result)
        self.assertLess(len(result), 3000)

    def test_incomplete_model_shape_falls_back_without_mutating_artifact(self):
        console = DemoConsole()
        valid = {"entities": {}}
        output = StringIO()
        with redirect_stdout(output):
            console.artifact("db_schema", valid)
            console.show("Model proposal", '{"entities":[]}')
        self.assertIn("entities", output.getvalue())
        self.assertEqual(console.artifacts["db_schema"], valid)


if __name__ == "__main__":
    unittest.main()
