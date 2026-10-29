"""Step 10 orchestration: UI existence tests -> component repair -> regression.

Tests are rendered deterministically from the complete step 09 design. A shared
file agent implements one page at a time, with previously accepted page tests
included in its checks. Tests and compiler-owned wiring are supplied as read-only files."""

import json
from pathlib import Path

from infrastructure.shared.agent.files import FileWorkspace, source_paths, editable_sources
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.stages.frontend.ui.design import owners, page_context
from infrastructure.stages.frontend.ui.runtime import prepare_frontend, sync_pages
from infrastructure.stages.frontend.ui.testing import FrontendChecks, existence_suite, require_green, presentation_run_status, test_path
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import save_json, save_text

INSTRUCTIONS = """Implement the current page's UI Element (Data) Primitives.
All requirements' UI/data have already been designed. Preserve the complete canonical
design and previously accepted pages. Implement layout, style, labels, controls, default
data presentation and conditional visibility using the supplied UiPageProps.data.
Use Tailwind CSS utility classes directly in each component's className for layout,
colors, typography and spacing. Tailwind v4 is configured through the Vite plugin.
Use complete literal class strings, including arbitrary values when necessary; do not
construct utility names dynamically. Do not create component CSS files, CSS modules,
style tags or inline style objects. The global stylesheet is compiler-owned.
For a new page, choose its source path under task.new_file.directory; otherwise edit
implementation_path. Export Page, a named React component
accepting UiPageProps. Current source, types and tests are supplied once in files;
Other supplied writable frontend sources may be repaired to resolve compilation
or presentation regressions; preserve their existing behavior and the frozen tests.
the compiler owns routing and fixtures. Return complete file contents in edits.
Import UiPageProps from the compiler-owned frontend/src/ui-runtime.ts, using a correct
relative import. React/ReactDOM and Tailwind CSS are available; do not add dependencies.
Put data-testid=<stable UI ID> on the ACTUAL element, including the page root. A test ID
on a decorative wrapper does not substitute for the input/button/select/image itself.
Use semantic HTML and associated labels. Use prop.input_type and exact option/label text.
All designed UI elements must be represented, including structural containers. Static
text and visual evidence supply layout and style; do not paste a screenshot as the UI.
Read frontend values from data[var]; use type assertions as needed. Use defaultValue
and defaultChecked for native editable inputs. Do not add onChange, onClick, onSubmit,
effects, custom hooks, state transitions, validation, business navigation, API calls,
session restoration, localStorage or cookie changes. Triggers/events are intentionally
empty. The compiler suppresses native form submissions; ordinary structural href links
may identify the designed routes. Leave business-handler slots for the next script.
Respect prop.visible booleans and equality predicates. Fixture states are supplied
through data, not by detecting tests. Render list/conditional content from the supplied
data; production defaults must not become fake backend responses. Do not alter frozen
tests, compiler runtime/config, backend files, or .arc artifacts.
Preserve other pages' styles. The test gate runs TypeScript, Playwright for current and previously accepted pages. Repair until
GREEN; do not weaken tests or write an implementation that only works in tests.
"""

def implement_ui(arc_dir: Path, design: dict, model, console, report: dict, max_turns: int = 18,
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
            workspace = FileWorkspace.for_target(output, "page", pid,
                writable=editable_sources(output, "frontend/src"),
                references=source_paths(output, "frontend/src") + files +
                    ["frontend/package.json", "frontend/tsconfig.json"])
            agent = run_file_agent(model, INSTRUCTIONS, context, workspace, implementation_gate,
                max_turns, console, label + " / Implementation", feedback=current)
        accepted.append(pid)
        report["pages"][pid].update({"status": "GREEN", "turns": agent["turns"],
            "implementation_path": selected_path(output, "page", pid),
            "checks": {key: value for key, value in agent["checks"]["tests"].items() if key != "output"}})
        save_json(arc_dir / "ui_checks.json", report)
        console.show(label + " | GREEN", agent["checks"]["tests"]["output"])
    console.show("UI final regression", "Run all current pages' existence suites and build both frontend and backend for npm start. Business triggers/events remain empty.")
    final = checks.tests([test_path(pid) for pid in accepted])
    require_green(final)
    compiled = checks.typecheck([test_path(pid) for pid in accepted])
    if compiled["returncode"]:
        raise ValueError(compiled["output"])
    built = checks.build()
    if built["returncode"]:
        raise ValueError(built["output"])
    report.update({"status": "GREEN", "summary": {"pages": len(accepted), "tests": final["passed"], "failed": final["failed"]}})
    save_json(arc_dir / "ui_checks.json", report)
    return report
