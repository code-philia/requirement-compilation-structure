"""Step 10 orchestration: UI existence tests -> component repair -> regression.

Tests are rendered deterministically from the complete step 09 design. A shared
file agent implements one page at a time, with previously accepted page tests
included in its checks. Trusted tests and compiler-owned wiring stay frozen."""

import json
from pathlib import Path

from infrastructure.shared.agent.files import FileTools, project_structure
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.traceability import FileIndex
from infrastructure.stages.frontend.ui.design import owners, page_context
from infrastructure.stages.frontend.ui.runtime import OWNED, prepare_frontend, sync_pages
from infrastructure.stages.frontend.ui.testing import FrontendChecks, assert_frozen, existence_suite, frozen_files, require_green, require_red, test_path
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import save_json, save_text

INSTRUCTIONS = """Implement ONLY the current page's UI Element (Data) Primitives.
All requirements' UI/data have already been designed. Preserve the complete canonical
design and previously accepted pages. Implement layout, style, labels, controls, default
data presentation and conditional visibility using the supplied UiPageProps.data.
Use Tailwind CSS utility classes directly in each component's className for layout,
colors, typography and spacing. Tailwind v4 is configured through the Vite plugin.
Use complete literal class strings, including arbitrary values when necessary; do not
construct utility names dynamically. Do not create component CSS files, CSS modules,
style tags or inline style objects. The global stylesheet is compiler-owned.
You choose component/helper filenames under frontend/src. The compiler supplies
complete current file contents each turn; edit only supplied existing files or create
new files. There is no file-reading tool. Use edit_files and entrypoint:{path,export} for a
named React component accepting UiPageProps; the compiler owns routing and fixtures.
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
Preserve other pages' styles. The test gate runs TypeScript, a presentation
boundary check and Playwright for current and previously accepted pages. Repair until
GREEN; do not weaken tests or write an implementation that only works in tests.
"""

# This is a teaching phase check, not a general JavaScript security analyzer.
PRESENTATION_CHECK = r'''
import ts from "typescript";
import fs from "node:fs";
const errors = [];
for (const path of process.argv.slice(1)) {
  const source = ts.createSourceFile(path, fs.readFileSync(path, "utf8"), ts.ScriptTarget.Latest, true,
    /\.[jt]sx$/.test(path) ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const visit = node => {
    if (ts.isJsxAttribute(node) && /^on[A-Z]/.test(node.name.getText(source)))
      errors.push(`${path}: event handlers belong to the next frontend stage`);
    if (ts.isCallExpression(node)) {
      const called = node.expression.getText(source);
      if (/(?:^|\.)(?:fetch|useEffect|useLayoutEffect|useState|useReducer|sendBeacon|setTimeout|setInterval)$/.test(called))
        errors.push(`${path}: ${called} is not part of UI/data presentation`);
    }
    if (ts.isIdentifier(node) && /^(?:XMLHttpRequest|WebSocket|EventSource|localStorage|sessionStorage)$/.test(node.text))
      errors.push(`${path}: browser effects belong to the next frontend stage`);
    if (ts.isPropertyAccessExpression(node) && node.getText(source) === "document.cookie")
      errors.push(`${path}: cookies belong to the next frontend stage`);
    ts.forEachChild(node, visit);
  };
  visit(source);
}
if (errors.length) { console.error([...new Set(errors)].join("\n")); process.exitCode = 1; }
'''


def implement_ui(arc_dir: Path, design: dict, model, console, report: dict, max_turns: int = 18,
        images: dict | None = None, requirement_contexts: dict | None = None) -> dict:
    """Implement the complete saved UI/data design through component-existence TDD.

    Prepare the project and browser, generate and freeze presence tests, then
    repair model-selected page components until checks pass. Update the caller's
    report and file index; runtime wiring remains compiler-owned."""
    output = arc_dir.parent.resolve()
    index = FileIndex(output)
    prepare_frontend(output, index)
    sync_pages(output, design, index)
    console.show("UI TDD preparation | Dependencies", "Install workspace dependencies and Playwright Chromium. No backend is started.")
    install_dependencies(output)
    checks = FrontendChecks(output)
    checks.install_browser()
    config_paths = ["frontend/playwright.ui.config.ts", "frontend/src/ui-runtime.ts", "frontend/src/main.tsx", "frontend/src/style.css",
        "frontend/tsconfig.json", "frontend/vite.config.ts", "frontend/package.json", "package.json"]
    frozen = frozen_files(output, config_paths)
    accepted = []
    report["status"] = "IMPLEMENTING"
    save_json(arc_dir / "ui_checks.json", report)
    for number, pid in enumerate(design["pages"], 1):
        module, uses = f"frontend:page:{pid}", owners(design, pid)
        relative = test_path(pid)
        suite = existence_suite(design, pid)
        save_text(output / relative, suite)
        index.record([relative], uses, f"tests:ui:{pid}")
        frozen.update(frozen_files(output, [relative]))
        report["pages"][pid] = {"status": "TESTS_READY", "requirements": uses, "test_path": relative}
        save_json(arc_dir / "ui_checks.json", report)
        label = f"UI {number}/{len(design['pages'])} {pid}"
        console.show(label + " | Existence tests before implementation", suite)
        files = [test_path(key) for key in [*accepted, pid]]

        def implementation_checks():
            """Refresh page registration and check selected page tests plus the frontend TypeScript sources."""
            assert_frozen(output, frozen)
            sync_pages(output, design, index)
            compiled = checks.typecheck(files)
            if compiled["returncode"]:
                return {"typecheck": compiled, "presentation": None, "tests": None}
            sources = sorted({path for key in [*accepted, pid]
                for path in index.files_for(module=f"frontend:page:{key}")
                if path not in OWNED and Path(path).suffix in {".ts", ".tsx", ".js", ".jsx"} and (output / path).is_file()})
            presentation = checks.execute(["--input-type=module", "-e", PRESENTATION_CHECK, *sources])
            presentation.pop("stdout", None)
            if presentation["returncode"]:
                return {"typecheck": compiled, "presentation": presentation, "tests": None}
            tested = checks.tests(files)
            assert_frozen(output, frozen)
            return {"typecheck": compiled, "presentation": presentation, "tests": tested}

        def implementation_gate():
            """Accept the current page only after test integrity, compilation, and presence tests pass."""
            if module not in index.data["entrypoints"]:
                raise ValueError("Select a React page component using edit_files.entrypoint")
            result = implementation_checks()
            for kind in ("typecheck", "presentation"):
                if result[kind] and result[kind]["returncode"]:
                    raise ValueError(f"{kind} failed: {result[kind]['output']}")
            require_green(result["tests"])
            return result

        # Compile tests separately before deciding whether browser failure is RED.
        current = implementation_checks()
        if current["typecheck"]["returncode"]:
            if module not in index.data["entrypoints"]:
                raise ValueError(f"UI infrastructure/test compilation failed before implementation: {current['typecheck']['output']}")
        elif current["tests"] is not None:
            if current["tests"]["returncode"]:
                require_red(current["tests"])
                report["pages"][pid]["status"] = "RED_CONFIRMED"
                console.show(label + " | RED: key UI components are missing", current["tests"]["output"])
            else:
                require_green(current["tests"])
        save_json(arc_dir / "ui_checks.json", report)
        if current["tests"] and current["tests"]["returncode"] == 0 and module in index.data["entrypoints"]:
            agent = {"turns": 0, "checks": implementation_gate()}
        else:
            context = {"page": page_context(design, pid),
                "requirements": [(requirement_contexts or {}).get(rid, {"id": rid}) for rid in uses],
                "visual_references": {iid: (images or {})[iid] for iid in design["pages"][pid]["images"]},
                "module_id": module, "project_structure": project_structure(output, "frontend"),
                "props_contract": (output / "frontend/src/ui-runtime.ts").read_text(),
                "frozen_existence_tests": suite, "initial_feedback": current,
                "triggers": {}, "events": {}}
            tools = FileTools(output, None, implementation_checks, roots=("frontend/src",), read_roots=("frontend",),
                context_files=("frontend/src/ui-runtime.ts", "frontend/src/main.tsx", "frontend/src/App.tsx",
                    "frontend/src/style.css", "frontend/package.json", "frontend/tsconfig.json"),
                protected=OWNED, index=index, requirements=uses, module=module)
            agent = run_file_agent(model, INSTRUCTIONS, context, tools, implementation_gate, max_turns, console, label + " / Implementation")
        accepted.append(pid)
        report["pages"][pid].update({"status": "GREEN", "turns": agent["turns"],
            "entrypoint": index.data["entrypoints"][module],
            "checks": {key: value for key, value in agent["checks"]["tests"].items() if key != "output"}})
        save_json(arc_dir / "ui_checks.json", report)
        console.show(label + " | GREEN", agent["checks"]["tests"]["output"])
    console.show("UI final regression", "Run all current pages' existence suites and build both frontend and backend for npm start. Business triggers/events remain empty.")
    # Remove only obsolete compiler-owned UI suites; preserve unlisted user tests.
    current_tests = {test_path(pid) for pid in accepted}
    for module, paths in index.data["modules"].items():
        if module.startswith("tests:ui:"):
            for relative in set(paths) - current_tests:
                target = (output / relative).resolve()
                if target.is_relative_to(output / "frontend/tests/ui") and target.name.endswith(".spec.ts"):
                    target.unlink(missing_ok=True)
    final = checks.tests([test_path(pid) for pid in accepted])
    require_green(final)
    compiled = checks.typecheck([test_path(pid) for pid in accepted])
    if compiled["returncode"]:
        raise ValueError(compiled["output"])
    built = checks.build()
    if built["returncode"]:
        raise ValueError(built["output"])
    assert_frozen(output, frozen)
    report.update({"status": "GREEN", "summary": {"pages": len(accepted), "tests": final["passed"], "failed": final["failed"]}})
    save_json(arc_dir / "ui_checks.json", report)
    return report
