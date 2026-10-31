"""Step 12 orchestration: scenario test generation -> trigger repair -> regression.

For each leaf requirement, one agent generates key E2E cases and another repairs
the trigger implementation. Complete that requirement before advancing; include
accepted functional smoke scenarios in regression checks."""

import json

from infrastructure.shared.agent.files import source_paths, editable_sources
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.stages.frontend.triggers.e2e_runtime import FIXTURE, prepare_e2e
from infrastructure.stages.frontend.triggers.testing import E2EChecks, require_behavioral_red, test_path
from infrastructure.stages.frontend.triggers.runtime import sync_triggers, prepare_trigger_paths
from infrastructure.stages.frontend.ui.runtime import prepare_frontend
from infrastructure.stages.frontend.ui.testing import require_green
from infrastructure.stages.backend.testing import BackendChecks, require_green as require_backend_green
from infrastructure.stages.frontend.triggers.design import api_ids, trigger_obligations, relevant_pages
from infrastructure.stages.frontend.triggers.scope import TriggerCheckFailure, model_context
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import save_json
from infrastructure.stages.frontend.ui.design import page_context, page_elements


def scenario_context(ui, design, rid):
    """Include direct requirement triggers and required page-entry lifecycle behavior."""
    pages = set(relevant_pages(ui, rid))
    while True:
        elements = {uid for pid in pages for uid in page_elements(ui, pid)}
        tids = set(design["requirements"].get(rid, [])) | {
            tid for tid, trigger in design["triggers"].items()
            if trigger["source"] in elements and trigger["event"] == "mount"}
        targets = {action.get("ui") for tid in tids for action in design["triggers"][tid]["action"] if action["kind"] == "ui"}
        destinations = {pid for pid, page in ui["pages"].items() if page["root"] in targets}
        hrefs = {ui["elements"][uid]["prop"].get("href") for uid in elements}
        destinations.update(pid for pid, page in ui["pages"].items() if page["route"] in hrefs)
        if destinations.issubset(pages):
            return {"page_subtrees": {pid: page_context(ui, pid) for pid in sorted(pages)},
                "triggers": {tid: design["triggers"][tid] for tid in sorted(tids)}}
        pages.update(destinations)


def test_run_status(result):
    """Route existing frontend runtime failures to code repair, not to test rewriting or valid RED."""
    if result["returncode"] == 0:
        require_green(result)
        return "GREEN"
    headlines = [error.split("\n", 1)[0] for error in result.get("failures", [])]
    if not result.get("errors") and not result.get("skipped") and not result.get("flaky") and result.get("failed") and any("E2E_RUNTIME_ERROR:" in error for error in headlines) and not any("E2E_BACKEND_ERROR:" in error or "E2E_NETWORK_ERROR:" in error or "browserType.launch" in error for error in headlines):
        return "REPAIR_REQUIRED"
    require_behavioral_red(result)
    return "RED_CONFIRMED"


TEST_INSTRUCTIONS = """Write a small Playwright functional smoke suite for the CURRENT requirement.
The goal is to verify that real UI input reaches the backend API and its result is
reflected in the application. Backend contract details were already tested in step 08;
UI presentation was already tested in step 10.

Normally write one primary successful workflow. Add a second case only for a critical
business rejection or anonymous state required by this requirement. Stay within max_tests;
do not fill the quota with field combinations or exhaustive branches. A successful
workflow may include navigation and reload when those are part of this requirement.
Destination pages and their mount triggers are supporting context, not instructions
to test other requirements' registration, login or logout workflows in this suite.

Create the .spec.ts target using task.new_file or update test_path. Import test and
expect from frontend/tests/e2e/support/context.ts with a relative .js import. Tests use
async ({page,database}) callbacks. Use the supplied test utility definitions and actual
backend source to understand fixture signatures and stored-data conventions. The fixture
resets a real isolated SQLite database before each case. Seed only necessary Given rows
with parameterized SQL and valid values; bind booleans as 0/1. Do not use another API to
manufacture Given state.

Drive actions through the browser, without mocks or injected UI state. Prefer supplied
UI IDs for stable selectors. Assert the visible business result with retrying Playwright
assertions, then check a small persisted business outcome only when necessary. Do not
assert every DB field, full-table snapshots, exact cookie/hash encodings, generated IDs,
timestamps, decorative text, styling or intermediate loading states. If deletion versus
soft invalidation is not specified, assert the observable session behavior instead of
choosing one database strategy. Do not invent wording or storage policies.

Tests still need real assertions and must not be skipped or weakened to pass. During
test generation, fix test syntax, fixtures or invalid selectors. Missing application
behavior is valid RED; retain that case for implementation. Runtime failures in supplied
application sources are implementation feedback, not a reason to rewrite the expected
business result. Compilation and a real browser run check the suite before code repair.
"""

IMPLEMENT_INSTRUCTIONS = """Implement the requirement's frontend triggers together against its E2E tests.
The task supplies the current requirement's triggers, supporting page-entry behavior,
actual frontend/backend source files. Application sources are writable according to
files; runtime wiring, schema and frozen tests are references. You may update multiple
pages, API handlers and helpers in the same edits list. Complete the functional path:
UI event -> frontend values -> API params/query/body -> real backend response -> shared
frontend state -> visible result and navigation. Use the actual supplied source and API
contract to resolve field names, types, status branches and stored-data conventions.
Implement this requirement's behavior; supporting page context does not require building
unrelated workflows early. Keep responses short by editing only files that need changes.
implementation_paths maps each trigger to its supplied writable file; null file content
means that file must be created. Return all required implementations in one edits list.
Export handle(context: UiTriggerContext): void | Promise<void> from
one source file per trigger, importing UiTriggerContext from frontend/src/ui-runtime.ts.
Ordinary helper functions may be shared through supplied writable sources.

The compiler captures native events, synchronizes UI input, registers handlers, owns
central frontend data and provides routing/API access. UiTriggerContext contains:
- data: current frontend variable values, exposed as a readonly record.
- input: optional value (string), checked (boolean) and key (string) for the native event.
- trigger: {id, source, event}.
- update(patch): merge frontend variable values into shared state.
- api(apiId, {params, query, body, headers, credentials}): perform the canonical HTTP call
  and return {status, body:unknown, headers}.
- navigate(pageId): navigate using a PAGE ID from page_subtrees, not its root ELEMENT ID.
  Resolve a navigation action's target root to its owning page through page_subtrees.

Implement the guard, ordered action conditions, request construction, response handling,
value conversion, UI updates and navigation in ordinary code. read and write describe frontend
data dependencies; obligations describes DB effects derived from API calls, not another
field mapping to implement literally. Native checkbox values are booleans and other input
values are strings; convert numbers explicitly when the API requires them.
Use context.api for business requests. For cookie-based contracts, the browser handles
cookies automatically; do not manually set Cookie or read HttpOnly credentials. Preserve
specified comparisons and failure-without-writes. Handle expected failures visibly and
surface unexpected errors rather than fabricating successful responses.

Pages remain presentational; avoid duplicate handlers or test detection. Repair any
supplied writable frontend source needed for actual behavior, preserving existing UI IDs,
styles and accepted workflows. Files permissions define editable sources; tests,
SQL, designs and compiler wiring remain references. Related API handlers and helpers
are supplied writable for integration fixes; backend tests remain read-only. Compilation,
functional smoke regressions and the final build accept the requirement implementation. Use their feedback to repair code
without weakening tests or hardcoding fixture values.
"""


def run_trigger_tdd(arc_dir, tree, schema, backend, ui, design, images, contexts,
        model, console, report, max_turns=10, max_tests=2):
    """Implement design one requirement at a time through real-app E2E TDD.

    Prepare dependencies/runtime, generate and freeze key scenario tests, then
    activate and repair the current trigger implementations before advancing. Regress
    accepted smoke scenarios, build the app, and update the caller's report."""
    output = arc_dir.parent.resolve()
    prepare_frontend(output)
    prepare_e2e(output, backend)
    sync_triggers(output, ui, design, backend, [])
    console.show("E2E preparation | Dependencies", "Install workspace dependencies and Chromium. Each browser run owns a new real test database; production data is not used.")
    install_dependencies(output)
    checks = E2EChecks(output, max_tests)
    checks.install_browser()
    accepted, implemented = [], set()
    selection = SourceFiles(output, ui)
    backend_selection = SourceFiles(output, root="backend/src", tests_root="backend/tests")
    report["status"] = "IMPLEMENTING"
    save_json(arc_dir / "frontend_e2e.json", report)
    for number, rid in enumerate(tree.leaves, 1):
        tids = set(design["requirements"][rid])
        steps = tree.own_steps[rid]
        label = f"E2E requirement {number}/{len(tree.leaves)} {rid}"
        context = scenario_context(ui, design, rid)
        pages = context["page_subtrees"]
        if not pages and not tids:
            report["requirements"][rid] = {"status": "NO_TRIGGERS", "triggers": []}
            save_json(arc_dir / "frontend_e2e.json", report)
            continue
        context_tids = set(context["triggers"])
        targets = tids | (context_tids - implemented)
        active = implemented | context_tids
        relative = test_path(rid, output)
        called = {aid for trigger in context["triggers"].values() for aid in api_ids(trigger)}
        context["obligations"] = {tid: trigger_obligations(trigger, backend) for tid, trigger in context["triggers"].items()}
        context.update({"requirement": contexts[rid], "target_trigger_ids": sorted(targets),
            "backend_apis": {aid: backend["apis"][aid] for aid in sorted(called)}})
        console.show(label + " | Scenario context", json.dumps(context, ensure_ascii=False, indent=2))
        report["requirements"][rid] = {"status": "GENERATING_TESTS", "triggers": sorted(tids),
            "target_triggers": sorted(targets), "test_path": relative}
        save_json(arc_dir / "frontend_e2e.json", report)
        regression_files = [test_path(key, output) for key in [*accepted, rid]]
        sync_triggers(output, ui, design, backend, active)

        def generation_checks():
            """Typecheck selected tests; test_gate also runs the real application."""
            nonlocal relative, regression_files
            relative = test_path(rid, output)
            regression_files = [test_path(key, output) for key in [*accepted, rid]]
            return checks.typecheck(regression_files, full_source=False)

        def test_gate():
            """Accept generated tests only when their structure and compilation pass; allow behavioral RED before implementation."""
            compiled = generation_checks()
            if compiled["returncode"]:
                raise ValueError(compiled["output"])
            behavior = checks.tests([relative])
            try:
                status = test_run_status(behavior)
            except ValueError as error:
                raise TriggerCheckFailure("Repair invalid E2E tests or affected application sources", behavior) from error
            return {"typecheck": compiled, "behavior": behavior, "status": status}

        test_context = {**model_context(context), "schema": schema["entities"], "test_path": relative if (output / relative).is_file() else None,
            "max_tests": max_tests}
        test_workspace = selection.workspace(target=("e2e_test", rid), existing=relative,
            references=["frontend/src/ui-runtime.ts", FIXTURE, "backend/tests/support/context.ts",
                *source_paths(output, "frontend/src"), *source_paths(output, "backend/src")])
        agent = run_file_agent(model, TEST_INSTRUCTIONS, test_context,
            test_workspace, test_gate, max_turns, console, label + " / Test Generation",
            feedback_filter=lambda value: selection.feedback(test_workspace, value))
        report["requirements"][rid]["test_turns"] = agent["turns"]
        report["requirements"][rid]["test_path"] = relative

        workspace = None

        def implementation_checks():
            """Compile sources and run accepted functional scenarios; regress APIs if edited."""
            sync_triggers(output, ui, design, backend, active)
            compiled = checks.typecheck(regression_files)
            result = {"typecheck": compiled, "e2e": None}
            if compiled["returncode"]:
                return result
            if workspace and any(path.startswith("backend/src/") for path in workspace.changed_paths):
                api_checks = BackendChecks(output)
                result["backend_typecheck"] = api_checks.typecheck()
                if result["backend_typecheck"]["returncode"]:
                    return result
                suites = [path for aid in backend["apis"]
                    if (path := selected_path(output, "backend_test", aid))]
                if suites:
                    result["backend_tests"] = api_checks.tests(suites)
                    if result["backend_tests"]["returncode"]:
                        return result
            result["e2e"] = checks.tests(regression_files)
            return result

        def implementation_gate():
            """Require actual implementations, compilation and functional smoke results."""
            absent = [tid for tid in sorted(targets)
                if not (path := selected_path(output, "trigger", tid)) or not (output / path).is_file()]
            if absent:
                raise ValueError("Create all supplied trigger files before acceptance: " + ", ".join(absent))
            result = implementation_checks()
            try:
                for kind in ("typecheck", "backend_typecheck"):
                    if result.get(kind) and result[kind]["returncode"]:
                        raise ValueError(result[kind]["output"])
                if "backend_tests" in result:
                    require_backend_green(result["backend_tests"])
                require_green(result["e2e"])
            except ValueError as error:
                raise TriggerCheckFailure("Functional integration or compilation failed", result) from error
            return result

        generated = agent["checks"]
        missing = [tid for tid in sorted(targets)
            if not (path := selected_path(output, "trigger", tid)) or not (output / path).is_file()]
        application_changed = any(path.startswith("frontend/src/") for path in test_workspace.changed_paths)
        current = {"typecheck": generated["typecheck"], "e2e": generated["behavior"]}
        report["requirements"][rid]["status"] = generated["status"]
        save_json(arc_dir / "frontend_e2e.json", report)
        # Reuse passing smoke results when test generation did not change application sources.
        if not missing and not application_changed and generated["status"] == "GREEN":
            agent = {"turns": 0, "checks": current}
        else:
            needs_implementation = bool(missing) or generated["status"] != "GREEN"
            feedback = current
            if not needs_implementation:
                try:
                    agent = {"turns": 0, "checks": implementation_gate()}
                except ValueError as error:
                    needs_implementation = True
                    feedback = getattr(error, "feedback", {"error": str(error)})
            if needs_implementation:
                task = {**model_context(context),
                    "implementation_paths": prepare_trigger_paths(output, context_tids)}
                workspace = selection.workspace(triggers=context_tids,
                    paths=[*editable_sources(output, "frontend/src"), "frontend/src/style.css"],
                    references=[relative, "backend/tests/support/context.ts",
                        *source_paths(output, "frontend/src"), *source_paths(output, "backend/src")])
                backend_selection.include(workspace, editable_sources(output, "backend/src"))

                def repair_feedback(value):
                    return selection.feedback(workspace, backend_selection.feedback(workspace, value))
                agent = run_file_agent(model, IMPLEMENT_INSTRUCTIONS, task, workspace,
                    implementation_gate, max_turns, console, label + " / Trigger Implementation",
                    feedback=feedback,
                    feedback_filter=repair_feedback)
        accepted.append(rid)
        reused = tids & implemented
        implemented.update(targets)
        result = agent["checks"]["e2e"]
        report["requirements"][rid].update({"status": "GREEN", "implementation_turns": agent["turns"],
            "steps": list(steps), "passed": result["passed"], "reused_triggers": sorted(reused)})
        save_json(arc_dir / "frontend_e2e.json", report)
        console.show(label + " | GREEN", result["output"])
    sync_triggers(output, ui, design, backend, implemented)
    console.show("Final frontend verification", "Run every functional smoke scenario, then build the complete frontend and backend.")
    final = checks.tests([test_path(rid, output) for rid in accepted]) if accepted else None
    if final is not None:
        require_green(final)
    built = checks.build()
    if built["returncode"]:
        raise ValueError(built["output"])
    report.update({"status": "GREEN", "summary": {"requirements": len(accepted), "triggers": len(implemented),
        "e2e_tests": final["passed"] if final else 0, "ui_tests": 0, "failed": 0}})
    save_json(arc_dir / "frontend_e2e.json", report)
    return report
