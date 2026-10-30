"""Frontend representation, publication, lifecycle dependencies and acceptance regressions."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import Mock

from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.frontend.context import load_ui_context
from infrastructure.stages.frontend.ui.design import apply_proposal, empty_design, page_context, normalize_design
from infrastructure.stages.frontend.ui.synthesis import synthesize_ui
from infrastructure.stages.frontend.ui.testing import presentation_run_status
from infrastructure.stages.frontend.triggers.design import empty_triggers, trigger_obligations
from infrastructure.stages.frontend.triggers.implementation import scenario_context, test_run_status
from infrastructure.utils.files import save_json, save_text


def node(kind, parent, data=(), mode=(), **props):
    return {"type": kind, "parent": parent, "data": list(data), "mode": list(mode), "prop": props}


def binding(dtype, initial, source):
    return {"dtype": dtype, "constraints": [], "initial": initial, "source": source}


def frontend_fixture():
    """A shared editor navigates to a later requirement's read-only summary page."""
    raw = {"id": "ROOT", "name": "Notes", "children": [
        {"id": rid, "name": rid, "description": description, "scenarios": [{"id": "SCN-" + rid,
            "steps": [{"id": "STEP-" + rid, "Given": "Existing notes in the database", "When": behavior, "Then": outcome}]}]}
        for rid, description, behavior, outcome in (
            ("REQ-A", "Save a note then navigate to /summary; empty text is rejected without writes.", "Enter text and submit the editor", "Show the updated count after navigation and refresh; show an error on rejection"),
            ("REQ-B", "Use the same editor and API to save another note.", "Enter another note and save", "Persist it and display the summary"),
            ("REQ-C", "The /summary page displays the count on every entry and refresh without writes.", "Open or refresh /summary", "Display the persisted count and allow returning to the editor"))]}
    tree = RequirementTree(raw)
    ui = {"pages": {
        "editor": {"name": "Editor", "route": "/", "root": "UI-EDITOR", "images": [], "fixtures": {"default": {}, "rejected": {"form.errorVisible": True, "form.error": "Text required"}}},
        "summary": {"name": "Summary", "route": "/summary", "root": "UI-SUMMARY", "images": [], "fixtures": {"default": {}, "loaded": {"summary.count": "2"}}}},
        "elements": {
            "UI-EDITOR": node("page", None), "UI-FORM": node("form", "UI-EDITOR"),
            "UI-TEXT": node("input", "UI-FORM", ["form.text"], ["user_write"], label="Note", input_type="text"),
            "UI-SAVE": node("button", "UI-FORM", text="Save"),
            "UI-ERROR": node("alert", "UI-EDITOR", ["form.error"], visible={"var": "form.errorVisible", "equals": True}),
            "UI-SUMMARY": node("page", None), "UI-COUNT": node("text", "UI-SUMMARY", ["summary.count"]),
            "UI-BACK": node("link", "UI-SUMMARY", text="Back", href="/")},
        "bindings": {"form.text": binding("string", "", "Native note input"), "form.error": binding("string", "", "API rejection message"),
            "form.errorVisible": binding("boolean", False, "Whether to show rejection"), "summary.count": binding("string", "Loading", "Count API response")},
        "requirements": {"ROOT": [], "REQ-A": ["UI-EDITOR", "UI-FORM", "UI-TEXT", "UI-SAVE", "UI-ERROR"],
            "REQ-B": ["UI-EDITOR", "UI-FORM", "UI-TEXT", "UI-SAVE", "UI-ERROR"], "REQ-C": ["UI-SUMMARY", "UI-COUNT", "UI-BACK"]},
        "steps": {"STEP-REQ-A": ["UI-TEXT", "UI-SAVE", "UI-ERROR"], "STEP-REQ-B": ["UI-TEXT", "UI-SAVE"], "STEP-REQ-C": ["UI-COUNT", "UI-BACK"]}}
    interactions = {'triggers': {'TR-INPUT': {'source': 'UI-TEXT',
                               'event': 'change',
                               'guard': None,
                               'read': [],
                               'action': [{'kind': 'ui',
                                           'description': 'Write input.value into form.text',
                                           'ui': 'UI-TEXT'}],
                               'write': ['form.text']},
                  'TR-SAVE': {'source': 'UI-FORM',
                              'event': 'submit',
                              'guard': None,
                              'read': ['form.text'],
                              'action': [{'kind': 'api',
                                          'api': 'API-SAVE',
                                          'description': 'POST form.text as body.text'},
                                         {'kind': 'ui',
                                          'description': 'On SAVE status 400 show its error message and set '
                                                         'form.errorVisible=true',
                                          'ui': 'UI-FORM'},
                                         {'kind': 'ui',
                                          'description': 'On SAVE status 200 navigate to summary',
                                          'ui': 'UI-SUMMARY'}],
                              'write': ['form.error', 'form.errorVisible']},
                  'TR-COUNT': {'source': 'UI-SUMMARY',
                               'event': 'mount',
                               'guard': None,
                               'read': [],
                               'action': [{'kind': 'api',
                                           'api': 'API-COUNT',
                                           'description': 'GET the current count'},
                                          {'kind': 'ui',
                                           'description': 'Write String(COUNT response.body.count) to '
                                                          'summary.count',
                                           'ui': 'UI-SUMMARY'}],
                               'write': ['summary.count']}},
     'requirements': {'ROOT': [],
                      'REQ-A': ['TR-INPUT', 'TR-SAVE'],
                      'REQ-B': ['TR-INPUT', 'TR-SAVE'],
                      'REQ-C': ['TR-COUNT']},
     'steps': {'STEP-REQ-A': ['TR-INPUT', 'TR-SAVE'],
               'STEP-REQ-B': ['TR-INPUT', 'TR-SAVE'],
               'STEP-REQ-C': ['TR-COUNT']}}
    backend = {"requirements": {"ROOT": [], "REQ-A": ["API-SAVE"], "REQ-B": ["API-SAVE"], "REQ-C": ["API-COUNT"]},
        "apis": {"API-SAVE": {"read": [], "write": ["Note.id", "Note.text"]}, "API-COUNT": {"read": ["Note.id", "Note.text"], "write": []}}}
    obligations = {"requirements": {rid: {"read": [] if rid != "REQ-C" else ["Note.id", "Note.text"],
        "write": ["Note.id", "Note.text"] if rid in {"REQ-A", "REQ-B"} else []} for rid in tree.requirements}}
    return raw, tree, ui, interactions, backend, obligations


class FrontendFlow(unittest.TestCase):
    def setUp(self):
        self.raw, self.tree, self.ui, self.interactions, self.backend, self.obligations = frontend_fixture()
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        self.arc = self.output / ".arc"

    def test_ui_design_accepts_model_metadata_without_type_or_semantic_gates(self):
        ui = deepcopy(self.ui)
        ui["bindings"]["form.text"]["dtype"] = "custom"
        ui["bindings"]["form.text"]["source"] = 123
        ui["pages"]["summary"]["route"] = "/"
        normalize_design(ui, self.tree)
        self.assertEqual(ui["bindings"]["form.text"]["source"], 123)


    def test_multiple_new_events_keep_model_paths_and_run_complete_acceptance(self):
        """Create every navigation dependency before accepting behavioral GREEN."""
        self.check_event_creation()

    def test_green_tests_do_not_skip_missing_or_deleted_event_files(self):
        """Even inadequate GREEN tests cannot bypass required implementation files."""
        from infrastructure.shared.project.entrypoints import remember_path
        remember_path(self.output, "trigger", "TR-COUNT", "frontend/src/deleted.ts")
        self.check_event_creation(early_green=True)

    def test_requirement_repair_can_edit_every_created_handler(self):
        """The behavior-repair phase can fix an earlier handler after all files exist."""
        self.check_event_creation(needs_repair=True)

    def check_event_creation(self, early_green=False, needs_repair=False):
        """Run the real orchestration with fake browser reports and model edits."""
        from unittest.mock import patch
        from infrastructure.shared.agent.files import FileWorkspace
        from infrastructure.shared.project.entrypoints import selected_path
        from infrastructure.shared.project.initialize import initialize_project
        from infrastructure.stages.frontend.triggers import implementation
        initialize_project(self.output)
        for pid in self.ui["pages"]:
            workspace = FileWorkspace.for_target(self.output, "page", pid)
            workspace.state()
            workspace.apply({"edits": [{"path": f"frontend/src/screens/{pid}.tsx",
                "content": "export function Page() {return null;}"}]})
        calls = []
        repaired = False
        def generate(instructions, payload):
            nonlocal repaired
            task = payload["task"]
            if "new_file" not in task:
                self.assertEqual(set(task["triggers"]), set(self.interactions["triggers"]))
                for eid in self.interactions["triggers"]:
                    path = selected_path(self.output, "trigger", eid)
                    self.assertTrue(payload["files"][path]["writable"], eid)
                self.assertNotIn("frontend/tests/ui/editor.spec.ts", payload["files"])
                repaired = True
                return {"edits": [{"path": selected_path(self.output, "trigger", "TR-INPUT"),
                    "content": "export function handle() { /* repaired */ }"}]}
            creation = task["new_file"]
            if creation["kind"] == "e2e_test":
                self.assertNotIn("frontend/src/screens/editor.tsx", payload["files"])
                self.assertFalse(payload["files"]["frontend/src/ui-runtime.ts"]["writable"])
            else:
                self.assertEqual(set(task["triggers"]), {creation["target"]})
                self.assertEqual(set(payload["files"]), {"frontend/src/ui-runtime.ts"})
            calls.append(deepcopy(task))
            suffix = ".spec.ts" if creation["kind"] == "e2e_test" else ".ts"
            path = f"{creation['directory']}/chosen/{creation['target']}{suffix}"
            return {"edits": [{"path": path, "content": "export function handle() {}"}]}
        checks, ui_checks = Mock(), Mock()
        checks.typecheck.return_value = {"returncode": 0, "output": "compiled"}
        checks.build.return_value = {"returncode": 0, "output": "built"}
        green = {"returncode": 0, "output": "passed", "passed": 1, "failed": 0,
            "skipped": 0, "flaky": 0, "errors": [], "failures": []}
        ui_checks.tests.return_value = green
        def test_events(files):
            if early_green or (all(selected_path(self.output, "trigger", eid) for eid in self.interactions["triggers"])
                    and (not needs_repair or repaired)):
                return green
            return {**green, "returncode": 1, "passed": 0, "failed": 1,
                "failures": ["expect(received).toBe(expected)"]}
        checks.tests.side_effect = test_events
        backend = deepcopy(self.backend)
        for aid, api in backend["apis"].items():
            api["signature"] = {"method": "POST", "path": "/api/" + aid, "name": aid}
        with patch.object(implementation, "install_dependencies"), \
                patch.object(implementation, "E2EChecks", return_value=checks), \
                patch.object(implementation, "FrontendChecks", return_value=ui_checks):
            report = implementation.run_trigger_tdd(self.arc, self.tree, {"entities": {}},
                backend, self.ui, self.interactions, {},
                {rid: {"id": rid} for rid in self.tree.leaves}, Mock(generate_json=generate),
                Mock(), {"requirements": {}}, max_turns=2)
        self.assertEqual(report["status"], "GREEN")
        creations = [task["new_file"]["target"] for task in calls if task["new_file"]["kind"] == "trigger"]
        self.assertEqual(creations, ["TR-COUNT", "TR-INPUT", "TR-SAVE"])
        self.assertEqual(report["requirements"]["REQ-A"]["implementation_turns"], 4 if needs_repair else 3)
        self.assertEqual(report["requirements"]["REQ-B"]["implementation_turns"], 0)
        self.assertIn("chosen/REQ-A.spec.ts", report["requirements"]["REQ-A"]["test_path"])
        self.assertGreater(checks.tests.call_count, 3)

    def test_single_trigger_context_supplies_frontend_data_and_derived_db_effects(self):
        from infrastructure.stages.frontend.triggers.scope import model_context
        context = scenario_context(self.ui, self.interactions, "REQ-A")
        context.update({"backend_apis": self.backend["apis"], "requirement": {"id": "REQ-A"},
            "obligations": {tid: trigger_obligations(tr, self.backend) for tid, tr in context["triggers"].items()}})
        selected = model_context(context, {"TR-SAVE"})
        self.assertEqual(set(selected["triggers"]), {"TR-SAVE"})
        self.assertEqual(selected["obligations"]["TR-SAVE"], {"read": [], "write": ["Note.id", "Note.text"]})
        self.assertEqual(set(selected["backend_apis"]), {"API-SAVE"})
        self.assertIn("form.text", selected["page_subtrees"]["editor"]["bindings"])
        self.assertNotIn("events", selected)
        self.assertNotIn("contracts", selected)


    def test_repair_scope_keeps_all_handlers_and_transitive_imports_writable(self):
        """Do not omit required handlers/helpers, including a missing indexed file."""
        from infrastructure.shared.project.entrypoints import remember_path
        from infrastructure.stages.frontend.triggers.scope import TriggerFiles
        paths = {"TR-INPUT": "frontend/src/events/input.ts", "TR-SAVE": "frontend/src/events/save.ts",
            "TR-COUNT": "frontend/src/events/deleted.ts"}
        for eid, relative in paths.items():
            remember_path(self.output, "trigger", eid, relative)
        save_text(self.output / paths["TR-INPUT"], 'import { value } from "../shared/value.js";')
        save_text(self.output / paths["TR-SAVE"], "export function handle() {}")
        save_text(self.output / "frontend/src/shared/value.ts", 'export { value } from "./nested";')
        save_text(self.output / "frontend/src/shared/nested/index.ts", 'import "../value.js"; export const value = 1;')
        save_text(self.output / "frontend/src/unrelated.ts", "unrelated")
        selected = TriggerFiles(self.output, self.ui)
        workspace = selected.workspace(triggers=set(paths))
        files = workspace.state()
        for relative in [*paths.values(), "frontend/src/shared/value.ts", "frontend/src/shared/nested/index.ts"]:
            self.assertTrue(files[relative]["writable"], relative)
        self.assertIsNone(files[paths["TR-COUNT"]]["content"])
        self.assertNotIn("frontend/src/unrelated.ts", files)
        self.assertFalse(files["frontend/src/ui-runtime.ts"]["writable"])

    def test_feedback_expands_page_dependencies_and_preserves_frozen_tests(self):
        """A locator/compiler error exposes repairable sources, never accepted tests."""
        from infrastructure.shared.project.entrypoints import remember_path
        from infrastructure.stages.frontend.triggers.scope import TriggerFiles
        page, helper = "frontend/src/screens/summary.tsx", "frontend/src/shared/count.ts"
        remember_path(self.output, "page", "summary", page)
        save_text(self.output / page, 'import { count } from "../shared/count.js";')
        save_text(self.output / helper, "export const count = 0;")
        frozen = "frontend/tests/e2e/accepted.spec.ts"
        save_text(self.output / frozen, "accepted assertions")
        selected = TriggerFiles(self.output, self.ui)
        generation = selected.workspace(target=("e2e_test", "REQ-A"))
        generation.state()
        generation.apply({"edits": [{"path": "frontend/tests/e2e/new.spec.ts", "content": "new assertions"}]})
        selected.feedback(generation, {"error": "generation error"})
        workspace = selected.workspace()
        result = selected.feedback(workspace, {"ui": {"returncode": 1,
            "failures": [f"UI-COUNT is not visible: {frozen}; frontend/tests/e2e/new.spec.ts"], "output": "duplicate reporter body"},
            "typecheck": {"returncode": 0, "output": "successful compiler output"}})
        files = workspace.state()
        self.assertTrue(files[page]["writable"])
        self.assertTrue(files[helper]["writable"])
        self.assertFalse(files[frozen]["writable"])
        self.assertFalse(files["frontend/tests/e2e/new.spec.ts"]["writable"])
        self.assertNotIn("output", result["ui"])
        self.assertEqual(result["typecheck"], {"returncode": 0})

    def test_agent_retry_receives_sources_identified_by_failed_checks(self):
        """A file omitted initially becomes writable before the next model repair request."""
        from infrastructure.shared.agent.loop import run_file_agent
        from infrastructure.stages.frontend.triggers.scope import TriggerFiles
        page = "frontend/src/screens/broken.tsx"
        helper = "frontend/src/shared/value.ts"
        save_text(self.output / page, 'import { value } from "../shared/value.js";')
        save_text(self.output / helper, "export const value = false;")
        selection = TriggerFiles(self.output)
        workspace = selection.workspace()
        calls = []
        def generate(instructions, payload):
            calls.append(payload)
            if len(calls) == 1:
                self.assertNotIn(page, payload["files"])
                return {"edits": []}
            self.assertTrue(payload["files"][page]["writable"])
            self.assertTrue(payload["files"][helper]["writable"])
            return {"edits": [{"path": helper, "content": "export const value = true;"}]}
        gate = Mock(side_effect=[ValueError(f"{page}(1,1): Type error"), {"green": True}])
        result = run_file_agent(Mock(generate_json=generate), "Repair", {}, workspace,
            gate, 2, Mock(), "Repair", feedback_filter=lambda value: selection.feedback(workspace, value))
        self.assertEqual(result["checks"], {"green": True})

    def test_runtime_types_survive_returning_to_presentation_stage(self):
        from infrastructure.shared.project.initialize import initialize_project
        from infrastructure.stages.frontend.ui.runtime import prepare_frontend
        from infrastructure.stages.frontend.triggers.runtime import sync_triggers
        from infrastructure.utils.files import read_source
        initialize_project(self.output)
        sync_triggers(self.output, {"pages": {}, "bindings": {}, "elements": {}},
            {"triggers": {}}, {"apis": {}}, [])
        before = read_source(self.output / "frontend/src/ui-runtime.ts")
        prepare_frontend(self.output)
        after = read_source(self.output / "frontend/src/ui-runtime.ts")
        self.assertEqual(before, after)
        self.assertIn("export interface UiTriggerContext", after)
        self.assertEqual(after.count("export type UiTriggerHandler"), 1)

    def test_synthesis_retries_without_publishing_rejected_state(self):
        requests = []
        def generate(instructions, payload):
            requests.append(deepcopy(payload))
            rid = payload["requirement"]["id"]
            page = "summary" if rid == "REQ-C" else "editor"
            context = page_context(self.ui, page)
            proposal = {"pages": {page: self.ui["pages"][page]} if rid != "REQ-B" else {},
                "elements": context["elements"] if rid != "REQ-B" else {}, "bindings": context["bindings"] if rid != "REQ-B" else {},
                "requirement_ui": self.ui["requirements"][rid], "step_ui": {sid: self.ui["steps"][sid] for sid in self.tree.own_steps[rid]}}
            return proposal
        contexts = {rid: {**record, "steps": [self.tree.steps[sid] for sid in self.tree.own_steps[rid]], "images": {}} for rid, record in self.tree.requirements.items()}
        result = synthesize_ui(self.arc, self.tree, {}, contexts, Mock(generate_json=generate), Mock())
        self.assertEqual(result, self.ui)
        self.assertEqual(len(requests), 3)
        self.assertNotIn("step_obligations", requests[0])

    def test_presentation_loader_has_no_report_policy(self):
        save_json(self.arc / "requirements.json", self.raw)
        save_json(self.arc / "visual_analysis.json", {})
        tree, images, contexts = load_ui_context(self.arc, self.output)
        self.assertEqual(tree.leaves, self.tree.leaves)
        self.assertEqual(images, {})
        self.assertNotIn("concatenated_steps", contexts["REQ-A"])

    def test_trigger_context_does_not_load_requirement_obligations_or_check_coverage(self):
        from infrastructure.stages.frontend.triggers.context import load_e2e_context
        for name, value in (("requirements", self.raw), ("visual_analysis", {}),
                ("db_schema", {"entities": {}}), ("backend_apis", self.backend),
                ("ui_design", self.ui), ("frontend_triggers", empty_triggers(self.tree))):
            save_json(self.arc / (name + ".json"), value)
        self.assertFalse((self.arc / "db_obligations.json").exists())
        _, _, backend, _, triggers, _, _ = load_e2e_context(self.arc, self.output)
        self.assertEqual(backend, self.backend)
        self.assertEqual(triggers["triggers"], {})

    def test_trigger_db_effects_are_derived_without_frontend_coverage_validation(self):
        from infrastructure.stages.frontend.triggers.design import apply_decomposition
        trigger = deepcopy(self.interactions["triggers"]["TR-SAVE"])
        trigger["action"] = [{"kind": "api", "api": "API-COUNT", "description": "Read count"}]
        result = apply_decomposition(empty_triggers(self.tree),
            {"triggers": {"T": trigger}, "requirement_triggers": ["T"], "step_triggers": {}}, "REQ-A")
        self.assertEqual(trigger_obligations(result["triggers"]["T"], self.backend),
            {"read": ["Note.id", "Note.text"], "write": []})
        self.assertEqual(result["triggers"]["T"]["read"], ["form.text"])

    def test_trigger_synthesis_only_retries_json_and_has_no_contract_pass(self):
        from infrastructure.stages.frontend.triggers.synthesis import synthesize_triggers
        calls = []

        def generate(instructions, payload):
            calls.append(deepcopy(payload))
            if len(calls) == 1:
                raise json.JSONDecodeError("Invalid JSON", "{broken", 1)
            rid = payload["requirement"]["id"]
            ids = self.interactions["requirements"][rid]
            return {"triggers": {tid: self.interactions["triggers"][tid] for tid in ids},
                "requirement_triggers": ids, "step_triggers": {}}

        result = synthesize_triggers(self.arc, self.ui, self.tree, self.backend,
            self.tree.requirements, Mock(generate_json=generate), Mock())
        self.assertEqual(len(calls), 4)
        self.assertIn("correction", calls[1])
        self.assertTrue(all("obligations" not in call for call in calls))
        self.assertEqual(set(result), {"triggers", "requirements", "steps"})
        self.assertTrue((self.arc / "frontend_triggers.json").is_file())


    def test_navigation_context_includes_later_page_mount_and_keeps_ownership(self):
        context = scenario_context(self.ui, self.interactions, "REQ-A")
        self.assertEqual(set(context["page_subtrees"]), {"editor", "summary"})
        self.assertEqual(set(context["triggers"]), {"TR-INPUT", "TR-SAVE", "TR-COUNT"})
        self.assertEqual(len(context["triggers"]), 3)
        self.assertEqual(self.interactions["requirements"]["REQ-A"], ["TR-INPUT", "TR-SAVE"])

    def test_backend_only_requirements_need_no_frontend_triggers(self):
        ui = normalize_design(empty_design(), self.tree)
        triggers = empty_triggers(self.tree)
        self.assertEqual(scenario_context(ui, triggers, "REQ-A")["triggers"], {})


    def test_frontend_runtime_failure_is_repair_not_test_regeneration(self):
        report = {"returncode": 1, "failed": 1, "errors": [], "failures": ["E2E_RUNTIME_ERROR: Broken handler"]}
        self.assertEqual(test_run_status(report), "REPAIR_REQUIRED")
        page_report = {**report, "failures": ["UI_RUNTIME_ERROR: Broken page"]}
        self.assertEqual(presentation_run_status(page_report), "REPAIR_REQUIRED")
        report["failures"] = ["E2E_BACKEND_ERROR: undeclared response"]
        with self.assertRaises(ValueError): test_run_status(report)


if __name__ == "__main__":
    unittest.main()
