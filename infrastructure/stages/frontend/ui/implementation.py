"""Step 10 orchestration: UI existence tests -> component repair -> regression.

Tests are rendered deterministically from the complete step 09 design. A shared
file agent implements one page at a time, with previously accepted page tests
included in its checks. Tests and compiler-owned wiring are supplied as read-only files."""

import json
from pathlib import Path

from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.stages.frontend.ui.design import owners, page_context
from infrastructure.stages.frontend.ui.runtime import prepare_frontend, sync_pages
from infrastructure.stages.frontend.ui.testing import FrontendChecks, existence_suite, require_green, presentation_run_status, test_path
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import save_json, save_text

INSTRUCTIONS = """Implement the current page from its UI/data design, requirement uses and visual_references.
Create the task.new_file target or update implementation_path. Export a named React
component Page accepting UiPageProps, imported from frontend/src/ui-runtime.ts using
a relative import. The compiler owns routing, initial data and display fixtures.

Render layout, style, labels, controls, lists and conditional content from data[var]
and static element props. Use the configured Tailwind utilities with complete class
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
and accepted page display tests, then a build. Implement the design without modifying
tests or compiler wiring to bypass failures.
"""

def implement_ui(arc_dir: Path, design: dict, model, console, report: dict, max_turns: int = 10,
        images: dict | None = None, requirement_contexts: dict | None = None) -> dict:
    """Implement the complete saved UI/data design through component-existence TDD.

    Prepare the project and browser, generate and freeze presence tests, then
    repair model-selected page components until checks pass. Update the caller's
    report; runtime wiring remains compiler-owned."""
    output = arc_dir.parent.resolve()
    prepare_frontend(output)
    sync_pages(output, design)
    console.show("UI TDD preparation | Dependencies", "Install workspace dependencies and Playwright Chromium. No backend is started.")
    install_dependencies(output)
    checks = FrontendChecks(output)
    checks.install_browser()
    accepted = []
    selection = SourceFiles(output, design)
    report["status"] = "IMPLEMENTING"
    save_json(arc_dir / "ui_checks.json", report)
    for number, pid in enumerate(design["pages"], 1):
        uses = owners(design, pid)
        relative = test_path(pid)
        suite = existence_suite(design, pid)
        save_text(output / relative, suite)
        report["pages"][pid] = {"status": "TESTS_READY", "requirements": uses, "test_path": relative}
        save_json(arc_dir / "ui_checks.json", report)
        label = f"UI {number}/{len(design['pages'])} {pid}"
        console.show(label + " | Existence tests before implementation", suite)
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

        # Compile tests separately before deciding whether browser failure is RED.
        current = implementation_checks()
        if current["tests"] is not None:
            report["pages"][pid]["status"] = presentation_run_status(current["tests"])
            console.show(label + " | " + report["pages"][pid]["status"], current["tests"]["output"])
        save_json(arc_dir / "ui_checks.json", report)
        if current["tests"] and current["tests"]["returncode"] == 0:
            agent = {"turns": 0, "checks": current}
        else:
            context = {"page": page_context(design, pid),
                "requirements": [{key: value for key, value in (requirement_contexts or {}).get(rid, {"id": rid}).items() if key != "images"} for rid in uses],
                "visual_references": {iid: (images or {})[iid] for iid in design["pages"][pid]["images"]},
                "implementation_path": selected_path(output, "page", pid)}
            workspace = selection.workspace(target=("page", pid),
                references=["frontend/src/ui-runtime.ts", relative, "frontend/package.json", "frontend/tsconfig.json"])
            agent = run_file_agent(model, INSTRUCTIONS, context, workspace, implementation_gate,
                max_turns, console, label + " / Implementation", feedback=current,
                feedback_filter=lambda value: selection.feedback(workspace, value))
        last_checks = agent["checks"]
        accepted.append(pid)
        report["pages"][pid].update({"status": "GREEN", "turns": agent["turns"],
            "implementation_path": selected_path(output, "page", pid),
            "checks": {key: value for key, value in agent["checks"]["tests"].items() if key != "output"}})
        save_json(arc_dir / "ui_checks.json", report)
        console.show(label + " | GREEN", agent["checks"]["tests"]["output"])
    console.show("UI final verification", "All pages passed the latest complete display regression; build the application.")
    final = last_checks["tests"]
    require_green(final)
    built = checks.build()
    if built["returncode"]:
        raise ValueError(built["output"])
    report.update({"status": "GREEN", "summary": {"pages": len(accepted), "tests": final["passed"], "failed": final["failed"]}})
    save_json(arc_dir / "ui_checks.json", report)
    return report
