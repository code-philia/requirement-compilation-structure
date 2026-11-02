"""Step 10 orchestration: UI existence tests -> component repair -> regression.

Tests are rendered deterministically from the complete step 09 design. A shared
file agent implements one page at a time, with previously accepted page tests
included in its checks. Generated tests are repairable against requirements; runtime wiring stays read-only."""

import json
from pathlib import Path

from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.recovery import implementation_task, final_checks, complete_report
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.stages.frontend.ui.design import owners, page_context
from infrastructure.stages.frontend.ui.runtime import prepare_frontend, sync_pages
from infrastructure.stages.frontend.ui.testing import FrontendChecks, existence_suite, require_green, test_path
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import save_json, save_text
from infrastructure.shared.project.git import checkpoint

INSTRUCTIONS = """Implement the current page from its UI/data design, requirement uses and visual_references.
Create the task.new_file target or update implementation_path. Export a named React
component Page accepting UiPageProps, imported from frontend/src/ui-runtime.ts using
a relative import. The compiler owns routing, initial data and display fixtures.

Render layout, style, labels, controls, lists and conditional content from data[var]
and static element props. Fixed labels, hints and captions are static props, not
dynamic state. State dependencies control rendering without exposing raw status values. Use the configured Tailwind utilities with complete class
strings; use installed React/ReactDOM without new dependencies. Reproduce visual
references through real elements, not a screenshot background in place of controls.
Put data-testid=ELEMENT_ID on each actual designed element, including the page root.
Use associated labels, specified input types/options, and role="alert" for alert elements.
Respect prop.visible booleans or variable-equality rules and original visible text.

Use defaultValue/defaultChecked for native editable controls. The host captures native
input/change events for user_write bindings: checkbox values become booleans and other
values remain strings. Do not add duplicate input handlers. This presentation task has
no business API calls, guards, session restoration or state transitions; triggers supply
those later. Native form submission is suppressed; structural links can use designed hrefs.
Render fixture data through the ordinary data prop, without inspecting test globals.

Repair supplied writable frontend dependencies when needed, preserving other pages
and behavior. Use the files map for permissions. The compiler runs TypeScript, current
and accepted page presence tests, then a build. Presence tests check element
availability in key states and required frontend data keys, not every attribute,
option representation, static caption or internal state value as visible text.
Diagnose feedback against the requirements. Correct writable tests that are wrong or
overly strict, preserving meaningful presence/state coverage; otherwise fix the page.
Runtime wiring and shared test utilities remain read-only.
"""

def implement_ui(arc_dir: Path, design: dict, model, console, report: dict, max_turns: int = 10,
        images: dict | None = None, requirement_contexts: dict | None = None) -> dict:
    """Implement the complete saved UI/data design through component-existence TDD.

    Prepare the project and browser, generate initial presence tests, then
    repair model-selected page components until checks pass. Update the caller's
    report; runtime wiring remains compiler-owned."""
    output = arc_dir.parent.resolve()
    prepare_frontend(output)
    sync_pages(output, design)
    console.show("UI TDD preparation | Dependencies", "Install workspace dependencies and Playwright Chromium. No backend is started.")
    install_dependencies(output)
    checks = FrontendChecks(output)
    checks.install_browser()
    checkpoint(output, stage="10", task="runtime", action="Prepare presentation host and browser tests",
        details={"pages": list(design["pages"])})
    accepted = []
    selection = SourceFiles(output, design)
    report["status"] = "IMPLEMENTING"
    save_json(arc_dir / "ui_checks.json", report)
    for number, pid in enumerate(design["pages"], 1):
        uses = owners(design, pid)
        relative = test_path(pid)
        suite = existence_suite(design, pid)
        if not (output / relative).is_file():
            save_text(output / relative, suite)
        report["pages"][pid] = {"status": "TESTS_READY", "requirements": uses, "test_path": relative}
        save_json(arc_dir / "ui_checks.json", report)
        label = f"UI {number}/{len(design['pages'])} {pid}"
        checkpoint(output, stage="10", task=pid, action="Publish UI existence suite before implementation",
            status="TESTS_READY", details={"test_path": relative, "requirements": uses,
                "display_states": list(design["pages"][pid]["fixtures"])})
        console.show(label + " | Existence tests before implementation", (output / relative).read_text(encoding="utf-8"))
        files = [test_path(key) for key in [*accepted, pid]]

        def implementation_checks():
            """Refresh page registration and check selected page tests plus the frontend TypeScript sources."""
            sync_pages(output, design)
            compiled = checks.typecheck(files)
            if compiled["returncode"]:
                return {"typecheck": compiled, "tests": None}
            tested = checks.tests(files)
            return {"typecheck": compiled, "tests": tested}

        def implementation_gate():
            """Accept the current page only after compilation and presence tests pass."""
            result = implementation_checks()
            for kind in ("typecheck",):
                if result[kind] and result[kind]["returncode"]:
                    raise ValueError(f"{kind} failed: {result[kind]['output']}")
            require_green(result["tests"])
            return result

        with implementation_task(output, report["pages"][pid], console, "10 / " + pid):
            # Compile tests separately before deciding whether browser failure is RED.
            try:
                current = implementation_checks()
            except (ValueError, RuntimeError) as error:
                current = {"error": str(error), "typecheck": None, "tests": None}
            if current["tests"] is not None:
                report["pages"][pid]["status"] = "GREEN" if not current["tests"]["returncode"] else "REPAIR_REQUIRED"
                console.show(label + " | " + report["pages"][pid]["status"], current["tests"]["output"])
            save_json(arc_dir / "ui_checks.json", report)
            if current["tests"] and current["tests"]["returncode"] == 0:
                agent = {"turns": 0, "checks": current}
            else:
                context = {"page": page_context(design, pid),
                    "requirements": [{key: value for key, value in (requirement_contexts or {}).get(rid, {"id": rid}).items() if key != "images"}
                        for rid in uses],
                    "visual_references": {iid: (images or {})[iid] for iid in design["pages"][pid]["images"]},
                    "implementation_path": selected_path(output, "page", pid)}
                workspace = selection.workspace(target=("page", pid),
                    references=["frontend/src/ui-runtime.ts", relative, "frontend/package.json", "frontend/tsconfig.json"])
                report["pages"][pid]["status"] = "IMPLEMENTING"
                agent = run_file_agent(model, INSTRUCTIONS, context, workspace, implementation_gate,
                    max_turns, console, label + " / Implementation", feedback=current,
                    feedback_filter=lambda value: selection.feedback(workspace, value))
            accepted.append(pid)
            report["pages"][pid].update({"status": "GREEN", "turns": agent["turns"],
                "implementation_path": selected_path(output, "page", pid),
                "checks": {key: value for key, value in agent["checks"]["tests"].items() if key != "output"}})
            save_json(arc_dir / "ui_checks.json", report)
            console.show(label + " | GREEN", agent["checks"]["tests"]["output"])
        save_json(arc_dir / "ui_checks.json", report)
    console.show("UI final verification", "All page tasks were attempted. Run display regression and build, retaining any failures.")
    files = [test_path(pid) for pid in design["pages"]]
    verification = final_checks(console,
        typecheck=(lambda: checks.typecheck(files), None),
        tests=(lambda: checks.tests(files), require_green),
        build=(checks.build, None))
    final = verification["tests"].get("result") or {}
    report["summary"] = {"pages": len(accepted), "tests": final.get("passed", 0), "failed": final.get("failed", 0)}
    complete_report(report, report["pages"].values(), verification)
    save_json(arc_dir / "ui_checks.json", report)
    return report
