"""Frontend representation, publication, lifecycle dependencies and acceptance regressions."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.frontend.context import load_ui_context
from infrastructure.stages.frontend.ui.design import apply_proposal, empty_design, page_context, validate_design
from infrastructure.stages.frontend.ui.synthesis import synthesize_ui
from infrastructure.stages.frontend.ui.testing import design_fingerprint, existence_suite, test_path, validate_ui_baseline, presentation_run_status
from infrastructure.stages.frontend.interactions.contracts import validate_contract
from infrastructure.stages.frontend.interactions.design import empty_interactions, validate_interactions
from infrastructure.stages.frontend.interactions.implementation import scenario_context, test_run_status
from infrastructure.stages.frontend.interactions.testing import validate_test_source
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
    interactions = {"triggers": {
        "TR-INPUT": {"source": "UI-TEXT", "event": "change", "action": "EV-INPUT"},
        "TR-SAVE": {"source": "UI-FORM", "event": "submit", "action": "EV-SAVE"},
        "TR-COUNT": {"source": "UI-SUMMARY", "event": "mount", "action": "EV-COUNT"}},
        "events": {
            "EV-INPUT": {"description": "Remember native text", "write": ["form.text"], "actions": [{"id": "SET-TEXT", "kind": "local", "description": "Write input.value into form.text"}]},
            "EV-SAVE": {"description": "Save or show the rejection", "write": ["form.error", "form.errorVisible"], "actions": [
                {"id": "SAVE", "kind": "api", "api": "API-SAVE", "description": "POST form.text as body.text"},
                {"id": "ERROR", "kind": "local", "description": "On SAVE status 400 show its error message and set form.errorVisible=true"},
                {"id": "OPEN-SUMMARY", "kind": "navigate", "page": "summary", "description": "On SAVE status 200 navigate to summary"}]},
            "EV-COUNT": {"description": "Load persisted count on entry", "write": ["summary.count"], "actions": [
                {"id": "COUNT", "kind": "api", "api": "API-COUNT", "description": "GET the current count"},
                {"id": "SHOW-COUNT", "kind": "local", "description": "Write String(COUNT response.body.count) to summary.count"}]}},
        "contracts": {"EV-INPUT": {"precondition": [], "postcondition": ["The current native text is available to submit."]},
            "EV-SAVE": {"precondition": [], "postcondition": ["A successful save persists one note and opens summary.", "A 400 response displays the error and performs no write."]},
            "EV-COUNT": {"precondition": [], "postcondition": ["Show the count on entry and refresh; leave the database unchanged."]}},
        "requirements": {"ROOT": [], "REQ-A": ["TR-INPUT", "TR-SAVE"], "REQ-B": ["TR-INPUT", "TR-SAVE"], "REQ-C": ["TR-COUNT"]},
        "steps": {"STEP-REQ-A": ["TR-INPUT", "TR-SAVE"], "STEP-REQ-B": ["TR-INPUT", "TR-SAVE"], "STEP-REQ-C": ["TR-COUNT"]}}
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

    def test_single_variable_definitions_and_full_record_updates(self):
        validate_design(self.ui, self.tree, {}, complete=True)
        page = page_context(self.ui, "editor")
        self.assertIn("form.errorVisible", page["bindings"])
        self.assertEqual(page["elements"]["UI-TEXT"]["data"], ["form.text"])
        before = deepcopy(self.ui)
        record = deepcopy(self.ui["elements"]["UI-TEXT"])
        record["prop"]["label"] = "Note text"
        proposal = {"pages": {}, "elements": {"UI-TEXT": record}, "bindings": {},
            "requirement_ui": self.ui["requirements"]["REQ-A"], "step_ui": {"STEP-REQ-A": self.ui["steps"]["STEP-REQ-A"]}}
        updated = apply_proposal(self.ui, proposal, "REQ-A", self.tree, {}, {"editor": page}, 3)
        self.assertEqual(updated["elements"]["UI-TEXT"]["prop"], {"label": "Note text", "input_type": "text"})
        self.assertEqual(self.ui, before)
        proposal["elements"]["UI-TEXT"] = {"prop": {"label": "Partial"}}
        with self.assertRaisesRegex(ValueError, "complete UI"):
            apply_proposal(self.ui, proposal, "REQ-A", self.tree, {}, {"editor": page}, 3)
        legacy = deepcopy(self.ui)
        legacy["bindings"]["form.text"]["owner"] = "UI-EDITOR"
        with self.assertRaises(ValueError): validate_design(legacy, self.tree, {})

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
            if len(requests) == 1:
                proposal = deepcopy(proposal)
                proposal["bindings"]["form.text"]["owner"] = "UI-EDITOR"
            return proposal
        contexts = {rid: {**record, "steps": [self.tree.steps[sid] for sid in self.tree.own_steps[rid]], "images": {}} for rid, record in self.tree.requirements.items()}
        result = synthesize_ui(self.arc, self.tree, {"entities": {}}, self.backend, {}, contexts, Mock(generate_json=generate), Mock())
        self.assertEqual(result, self.ui)
        self.assertEqual(len(requests), 4)
        self.assertIn("correction", requests[1])
        self.assertEqual(requests[1]["retrieved_pages"], {})
        self.assertNotIn("step_obligations", requests[0])

    def test_presentation_loader_and_design_fingerprint(self):
        save_json(self.arc / "requirements.json", self.raw)
        save_json(self.arc / "visual_analysis.json", {})
        tree, images, contexts = load_ui_context(self.arc, self.output)
        self.assertEqual(tree.leaves, self.tree.leaves)
        self.assertEqual(images, {})
        self.assertNotIn("concatenated_steps", contexts["REQ-A"])
        report = {"status": "GREEN", "design_hash": design_fingerprint(self.ui), "pages": {}}
        for pid in self.ui["pages"]:
            relative = test_path(pid)
            report["pages"][pid] = {"status": "GREEN", "test_path": relative}
            save_text(self.output / relative, existence_suite(self.ui, pid))
        save_json(self.arc / "ui_checks.json", report)
        validate_ui_baseline(self.arc, self.ui)
        changed = deepcopy(self.ui)
        changed["elements"]["UI-TEXT"]["prop"]["style"] = "larger spacing"
        self.assertEqual(existence_suite(changed, "editor"), existence_suite(self.ui, "editor"))
        with self.assertRaisesRegex(ValueError, "current UI/data"):
            validate_ui_baseline(self.arc, changed)

    def test_effects_and_input_wiring_without_repeated_rw_contracts(self):
        validate_interactions(self.interactions, self.ui, self.tree, {}, self.obligations, self.backend, self.tree.leaves, complete=True)
        for mutate in ("unknown_api", "duplicate_trigger", "missing_input", "legacy_read"):
            state = deepcopy(self.interactions)
            if mutate == "unknown_api": state["events"]["EV-SAVE"]["actions"][0]["api"] = "API-OTHER"
            elif mutate == "duplicate_trigger": state["triggers"]["TR-DUP"] = state["triggers"]["TR-INPUT"]
            elif mutate == "missing_input": state["events"]["EV-INPUT"]["write"] = []
            else: state["events"]["EV-SAVE"]["read"] = []
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                validate_interactions(state, self.ui, self.tree, {}, self.obligations, self.backend, self.tree.leaves)
        for eid, contract in self.interactions["contracts"].items(): validate_contract(eid, contract)
        with self.assertRaises(ValueError): validate_contract("EV", {"precondition": [], "postcondition": [], "actions": {}})

    def test_navigation_context_includes_later_page_mount_and_keeps_ownership(self):
        context = scenario_context(self.ui, self.interactions, "REQ-A")
        self.assertEqual(set(context["page_subtrees"]), {"editor", "summary"})
        self.assertEqual(set(context["events"]), {"EV-INPUT", "EV-SAVE", "EV-COUNT"})
        self.assertEqual(len(context["triggers"]), 3)
        self.assertEqual(self.interactions["requirements"]["REQ-A"], ["TR-INPUT", "TR-SAVE"])
        source = 'import {test,expect} from "./support/context.js"; test("STEP:STEP-REQ-A saves", async ({page}) => {await page.goto("/"); await expect(page.getByTestId("UI-EDITOR")).toBeVisible();});'
        validate_test_source(source, ["STEP-REQ-A"], 1)

    def test_backend_only_requirements_need_no_frontend_effect_coverage(self):
        ui = empty_design()
        ui["requirements"] = {rid: [] for rid in self.tree.requirements}
        ui["steps"] = {sid: [] for sid in self.tree.steps}
        validate_design(ui, self.tree, {}, complete=True)
        interactions = empty_interactions(self.tree)
        validate_interactions(interactions, ui, self.tree, {}, self.obligations, self.backend, self.tree.leaves, complete=True)
        self.assertEqual(scenario_context(ui, interactions, "REQ-A")["events"], {})

    def test_frontend_runtime_failure_is_repair_not_test_regeneration(self):
        report = {"returncode": 1, "failed": 1, "errors": [], "failures": ["E2E_RUNTIME_ERROR: Broken handler"]}
        self.assertEqual(test_run_status(report), "REPAIR_REQUIRED")
        page_report = {**report, "failures": ["UI_RUNTIME_ERROR: Broken page"]}
        self.assertEqual(presentation_run_status(page_report), "REPAIR_REQUIRED")
        report["failures"] = ["E2E_BACKEND_ERROR: undeclared response"]
        with self.assertRaises(ValueError): test_run_status(report)


if __name__ == "__main__":
    unittest.main()
