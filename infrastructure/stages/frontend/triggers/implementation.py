"""Step 12 orchestration: scenario test generation -> trigger repair -> regression.

For each leaf requirement, one agent generates key E2E cases and another repairs
the trigger implementation. Complete that requirement before advancing; include
accepted scenarios and UI presence tests in regression checks."""

import json

from infrastructure.shared.agent.files import source_paths
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.stages.frontend.triggers.e2e_runtime import FIXTURE, prepare_e2e
from infrastructure.stages.frontend.triggers.testing import E2EChecks, require_behavioral_red, test_path
from infrastructure.stages.frontend.triggers.runtime import sync_triggers, prepare_trigger_paths
from infrastructure.stages.frontend.ui.runtime import prepare_frontend
from infrastructure.stages.frontend.ui.testing import FrontendChecks, require_green, test_path as ui_test_path
from infrastructure.stages.frontend.triggers.design import api_ids, trigger_obligations, relevant_pages
from infrastructure.stages.frontend.triggers.scope import TriggerCheckFailure, model_context
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import save_json
from infrastructure.stages.frontend.ui.design import page_context, page_elements


def scenario_context(ui, design, rid):
    """Include the requirement's triggers and navigation destination lifecycle triggers."""
    pages = set(relevant_pages(ui, rid))
    while True:
        elements = {uid for pid in pages for uid in page_elements(ui, pid)}
        tids = set(design["requirements"].get(rid, [])) | {
            tid for tid, trigger in design["triggers"].items() if trigger["source"] in elements}
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


TEST_INSTRUCTIONS = """Write Playwright E2E tests for the current requirement before implementing its triggers.
Requirements define expected business outcomes; use the API contracts, UI definitions
and scenarios for concrete fields, selectors and branches. Trigger descriptions and
derived DB obligations are context, not the sole test oracle or unconditional effects.

Create a .spec.ts target using task.new_file or update test_path. Import test and expect
from frontend/tests/e2e/support/context.ts using a relative .js import. Read the
supplied test utility definitions, including re-exported helpers, for their signatures
and fixture data conventions. Construct fixtures compatible with those conventions and
the API contract; do not guess helper arguments or substitute arbitrary encoded values.
Tests use async ({page,database}) callbacks. The fixture resets a real isolated
SQLite database before each case; seed Given rows with parameterized SQL and supplied
schema definitions. Bind booleans as 0/1.
Do not call another API to manufacture Given state.

Within max_tests, cover meaningful success, required rejection/unchanged data, navigation
and reload persistence when specified. Drive When behavior through the browser UI, not
direct HTTP calls, mocks or injected UI state. Assert visible results with Playwright's
retrying locator assertions, then independently query DB outcomes. For asynchronous
text and alerts, assert the expected content instead of only element presence; avoid
fixed sleeps or waiting for a network call that an unimplemented trigger never makes.
Passive network observations can supplement UI assertions when needed.
Do not assume random identifiers, hashes, timestamps or exact wording absent from the
requirement/API contract. Use real assertions without skipped/focused/expected-failure tests.

The current suite is writable; other files follow the supplied permissions. Failed
checks can expose existing frontend sources for repair. Fix invalid test code or fixtures
in this phase; repair existing writable application code when it causes runtime failures,
without implementing new triggers before their tests. Assertion RED for missing behavior
is valid, including navigation before its trigger exists. If fixture/runtime errors and
behavioral RED coexist, fix the fixture/runtime errors and retain the behavioral cases
and assertions for implementation. Do not delete or weaken them to make test generation
pass. Compiler-owned fixtures, runtime types, startup and DB isolation are
provided. TypeScript and real browser execution determine whether tests are usable;
implementation and regression acceptance follow separately.
"""

IMPLEMENT_INSTRUCTIONS = """Implement the requirement's frontend triggers together against its E2E tests.
The task supplies all needed triggers, including destination-page lifecycle behavior.
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
styles and accepted workflows. Files permissions define editable sources; tests, backend,
SQL, designs and compiler wiring remain references. Compilation and real E2E/UI
regressions accept the complete requirement implementation. Use their feedback to repair code
without weakening tests or hardcoding fixture values.
"""


def run_trigger_tdd(arc_dir, tree, schema, backend, ui, design, images, contexts,
        model, console, report, max_turns=5, max_tests=5):
    """Implement design one requirement at a time through real-app E2E TDD.

    Prepare dependencies/runtime, generate and freeze key scenario tests, then
    activate and repair the current trigger implementations before advancing. Regress
    accepted E2E/UI tests, build the app, and update the caller's report."""
    output = arc_dir.parent.resolve()
    prepare_frontend(output)
    prepare_e2e(output, backend)
    sync_triggers(output, ui, design, backend, [])
    console.show("E2E preparation | Dependencies", "Install workspace dependencies and Chromium. Each browser run owns a new real test database; production data is not used.")
    install_dependencies(output)
    checks, ui_checks = E2EChecks(output, max_tests), FrontendChecks(output)
    checks.install_browser()
    ui_files = [ui_test_path(pid) for pid in ui["pages"]]
    baseline = ui_checks.tests(ui_files)
    require_green(baseline)
    accepted, implemented = [], set()
    selection = SourceFiles(output, ui)
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
            return checks.typecheck([*regression_files, *ui_files], full_source=False)

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
                *source_paths(output, "backend/src/db")])
        agent = run_file_agent(model, TEST_INSTRUCTIONS, test_context,
            test_workspace, test_gate, max_turns, console, label + " / Test Generation",
            feedback_filter=lambda value: selection.feedback(test_workspace, value))
        report["requirements"][rid]["test_turns"] = agent["turns"]
        report["requirements"][rid]["test_path"] = relative

        def implementation_checks():
            """Refresh registrations and execute actual compilation, E2E and UI regressions."""
            sync_triggers(output, ui, design, backend, active)
            compiled = checks.typecheck([*regression_files, *ui_files])
            if compiled["returncode"]:
                return {"typecheck": compiled, "e2e": None, "ui": None}
            tested = checks.tests(regression_files)
            presence = ui_checks.tests(ui_files) if tested["returncode"] == 0 else None
            return {"typecheck": compiled, "e2e": tested, "ui": presence}

        def implementation_gate():
            """Accept current trigger implementations only after compilation and all required browser regressions pass."""
            absent = [tid for tid in sorted(targets)
                if not (path := selected_path(output, "trigger", tid)) or not (output / path).is_file()]
            if absent:
                raise ValueError("Create all supplied trigger files before acceptance: " + ", ".join(absent))
            result = implementation_checks()
            for kind in ("typecheck",):
                if result[kind] and result[kind]["returncode"]:
                    raise ValueError(result[kind]["output"])
            try:
                require_green(result["e2e"])
                require_green(result["ui"])
            except ValueError as error:
                raise TriggerCheckFailure("Requirement behavior or UI regression failed", result) from error
            return result

        generated = agent["checks"]
        missing = [tid for tid in sorted(targets)
            if not (path := selected_path(output, "trigger", tid)) or not (output / path).is_file()]
        application_changed = any(path.startswith("frontend/src/") for path in test_workspace.changed_paths)
        current = {"typecheck": generated["typecheck"], "e2e": generated["behavior"], "ui": baseline}
        report["requirements"][rid]["status"] = generated["status"]
        save_json(arc_dir / "frontend_e2e.json", report)
        # A pure test addition does not invalidate passed application/UI checks.
        # Any source edit or handler creation receives complete regression acceptance.
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
                workspace = selection.workspace(triggers=context_tids, references=[relative, "frontend/src/ui-runtime.ts"])
                agent = run_file_agent(model, IMPLEMENT_INSTRUCTIONS, task, workspace,
                    implementation_gate, max_turns, console, label + " / Trigger Implementation",
                    feedback=feedback,
                    feedback_filter=lambda value: selection.feedback(workspace, value))
        baseline = agent["checks"]["ui"]
        accepted.append(rid)
        reused = tids & implemented
        implemented.update(targets)
        result = agent["checks"]["e2e"]
        report["requirements"][rid].update({"status": "GREEN", "implementation_turns": agent["turns"],
            "steps": list(steps), "passed": result["passed"], "reused_triggers": sorted(reused)})
        save_json(arc_dir / "frontend_e2e.json", report)
        console.show(label + " | GREEN", result["output"])
    sync_triggers(output, ui, design, backend, implemented)
    console.show("Final frontend verification", "Run every generated E2E scenario and UI existence suite, then build the full application.")
    final = checks.tests([test_path(rid, output) for rid in accepted]) if accepted else None
    if final is not None:
        require_green(final)
    presence = ui_checks.tests(ui_files)
    require_green(presence)
    built = checks.build()
    if built["returncode"]:
        raise ValueError(built["output"])
    report.update({"status": "GREEN", "summary": {"requirements": len(accepted), "triggers": len(implemented),
        "e2e_tests": final["passed"] if final else 0, "ui_tests": presence["passed"], "failed": 0}})
    save_json(arc_dir / "frontend_e2e.json", report)
    return report
