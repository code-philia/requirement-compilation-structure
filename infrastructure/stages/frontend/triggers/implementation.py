"""Step 12 orchestration: scenario test generation -> trigger repair -> regression.

For each leaf requirement, one agent generates key E2E cases and another repairs
the trigger implementation. Complete that requirement before advancing; include
accepted functional smoke scenarios in regression checks."""

import json

from infrastructure.shared.agent.files import editable_application_path
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.recovery import implementation_task, final_checks, complete_report
from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.agent.discovery import project_index
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.stages.frontend.triggers.e2e_runtime import CONFIG, FIXTURE, prepare_e2e
from infrastructure.stages.frontend.triggers.testing import E2EChecks, test_path
from infrastructure.stages.frontend.ui.runtime import APPLICATION_ENTRYPOINTS, prepare_frontend
from infrastructure.stages.frontend.ui.testing import FrontendChecks, require_green, test_path as ui_test_path
from infrastructure.stages.backend.context import related_schema
from infrastructure.stages.backend.testing import BackendChecks, require_green as require_backend_green
from infrastructure.stages.frontend.triggers.design import api_ids, trigger_obligations
from infrastructure.stages.frontend.triggers.scope import TriggerCheckFailure, model_context
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import save_json
from infrastructure.stages.frontend.ui.design import page_context, page_elements
from infrastructure.shared.project.git import checkpoint


def scenario_context(ui, design, rid):
    """Reference this requirement's triggers and directly involved pages only."""
    triggers = {tid: design["triggers"][tid] for tid in design["requirements"].get(rid, [])}
    elements = set(ui["requirements"].get(rid, []))
    for trigger in triggers.values():
        elements.add(trigger["source"])
        for action in trigger["action"]:
            if action["kind"] == "ui":
                elements.add(action["ui"])
    pages = {}
    for pid in ui["pages"]:
        if elements.intersection(page_elements(ui, pid)):
            pages[pid] = page_context(ui, pid)
    return {"page_subtrees": pages, "triggers": triggers}


def editable_runtime_path(output, path):
    """Allow evidence-driven database runtime repairs alongside application repairs."""
    if editable_application_path(output, path):
        return True
    return (path.startswith("backend/src/db/") and path.endswith((".ts", ".sql"))
        and (output / path).is_file())


def test_run_status(result):
    """Pass every real failure to repair; do not guess its cause from error text."""
    try:
        require_green(result)
        if result.get("skipped") or result.get("flaky"):
            return "REPAIR_REQUIRED"
        return "GREEN"
    except ValueError:
        return "REPAIR_REQUIRED"


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
Use concrete URLs and object identities from the requirement's workflow and actual
application routing. A route pattern containing :id or {id} is not a literal URL.
Do not prescribe a component API, event dispatcher or routing library in the tests.
For a user action that requires one API operation, especially a mutation, observe its relevant HTTP
method/endpoint during that When action and check that it is not submitted twice. Also
check the required business outcome. Count only that operation, not page-entry reads,
unrelated calls, or retries/repeated operations explicitly required by the requirement.
Install request observation before the action; synchronize with its response and visible
completion. Do not add fixed sleeps or assert all application requests have count one.

Use edit_file to create the .spec.ts target under frontend/tests/e2e using task.file_target or update test_path. Import test and
expect from frontend/tests/e2e/support/context.ts with a relative .js import. Tests use
async ({page,database}) callbacks. Use the supplied test utility definitions and actual
backend source to understand fixture signatures and stored-data conventions. The fixture
resets a real isolated SQLite database and reapplies requirement-defined startup data before
each case. Inspect the relevant backend/src/db/seeds/ENTITY.sql when needed; reuse
prerequisite records and do not assume tables are empty. Do not rerun another requirement's
registration or content-creation flow just to prepare Given data. If this scenario requires
absence or a conflicting state, arrange only its relevant records in the isolated database
before the browser actions. Seed only additional necessary Given rows
with parameterized SQL and valid values; bind booleans as 0/1. Do not use another API to
manufacture Given state.

Drive actions through the browser, without mocks or injected UI state. Prefer supplied
UI IDs for stable selectors. Assert the visible business result with retrying Playwright
assertions, then check a small persisted business outcome only when necessary. Do not
assert every DB field, full-table snapshots, exact cookie/hash encodings, generated IDs,
timestamps, decorative text, styling or intermediate loading states. If deletion versus
soft invalidation is not specified, assert the observable session behavior instead of
choosing one database strategy. Do not invent wording or storage policies.
Use original requirement-defined UI names and roles exactly when they are explicit; do not
replace them with aliases learned from current application code. Conversely, do not invent
exact captions, placeholders or globally unique link names when the requirement does not
specify them. Scope navigation and business-object locators by their semantic purpose.

Tests still need real assertions and must not be skipped or weakened to pass. During
test generation, fix test syntax, fixtures or invalid selectors. Missing application
behavior is valid RED; retain that case for implementation. Runtime failures in supplied
application sources are implementation feedback, not a reason to rewrite the expected
business result. Compilation and a real browser run check the suite before code repair.
"""

IMPLEMENT_INSTRUCTIONS = """Implement the current requirement's interactions in the actual application.
Step 11's triggers are a reference prototype: preserve their requirement-defined behavior,
not a fixed handler/context ABI, event dispatcher, store or routing implementation.
Read the actual entrypoints, relevant components and supplied package/configuration first.
Use the project's framework and installed dependencies. You own component events, lifecycle
hooks, routing, state, input conversion, request construction and response integration.
The compiler does not regenerate App, route tables, handlers, stores or API clients.

Implement the full path: UI event -> actual input/object identity -> request params/query/
body/headers -> real backend API -> success/rejection response -> updated state and visible UI.
Use ordinary framework code: closures/callbacks, hooks, services or shared functions as
appropriate. You may implement several related reference triggers together in components
or helpers. No one-file-per-trigger rule, forced handle export, UiTriggerContext or central
registry is required. Keep code reusable and incrementally preserve previous requirements.

Preserve explicit original UI naming contracts during implementation and every repair:
labels, action names, headings, region names, required placeholders and semantic roles.
Keep wording, language, spelling and case unchanged; do not add prefixes, translate or
concatenate aliases. A required "Name" field stays "Name". Keep the visible label and
computed accessible name consistent; aria-label/aria-labelledby must not replace or extend
the required name. Original explicit requirements take precedence over generated design,
reference examples and existing incorrect code. Fix a naming violation in the application,
not by weakening an otherwise correct test. Unspecified wording remains your choice;
dynamic business names and user input must still reflect real data.

Before adding an event or effect, read the existing component and follow its current
UI -> callback/effect -> service -> HTTP call chain. Extend or reuse the existing owner
of that business operation. A new reference trigger ID does not require a new listener.
For a form, choose one submission owner; do not send the same mutation from both a
button's onClick and the form's onSubmit. Check bubbling handlers, parent callbacks,
native listeners and effects as well. Preserve submit-by-Enter and nested-icon clicks.
Clean up subscriptions, avoid repeated effect-driven mutations, and use operation-local
pending protection for rapid repeated submission when appropriate. Never use a global
URL-based deduplication cache to hide duplicate wiring or suppress legitimate operations.

For dynamic routes, use the actual router or application routing code to construct and
parse concrete parameters. Support direct entry, reload, navigation and back/forward as
required. Identify a clicked row from that row's actual data/callback, not a shared global
example object or event.target.value from an arbitrary nested icon/span. Carry the selected
identity through the URL/request/state consistently; encode URL values correctly.

Use framework-native form bindings. An input updates only its actual value field; other
variables in element.data may be read dependencies. Choose appropriate types/conversions
for numbers, dates, booleans, arrays and other controls. State changes, asynchronous loads,
reset/cancel and object switches must update the displayed controls. Do not rely on an
automatic compiler input/change handler or require defaultValue/defaultChecked everywhere.

Call the canonical backend interfaces with real HTTP, using existing request helpers or
new shared application helpers as appropriate. Preserve previous API request cases.
Respect response status/body/headers, empty bodies and browser-managed cookies. Do not
manually set browser Cookie headers or read HttpOnly credentials. Register event handling
only once; preserve action ordering, guards, rejection behavior and failure-without-writes.
Keep actual loaded data associated with the requested object. Initialize safe unloaded
state and requirement defaults; never seed UI state from reference images/test records.
Build edit drafts from real loaded objects and cancel to their snapshots. Handle expected
errors visibly and prevent stale requests from overwriting a later selection/result.

Only task.target_trigger_ids belong to this implementation task. Other controls on supplied
pages are context, not a demand to build future workflows. Required entry/loading behavior
should be explicitly associated by step 11. Read missing designs/sources on demand; do not
recursively implement all mount/navigation behavior of every reachable page. Preserve any
previously working supporting behavior. If a necessary dependency is missing, implement
only the minimal behavior needed for this requirement and explain it in diagnosis.

Preserve selectors and the presentation-test adapter in frontend/src/ui-runtime.ts.
presentationData exposes declared values to display tests without owning application state;
isPresentationTest identifies explicit display-only previews. Keep their data/effects
isolated from real API loading. Normal browser E2E must use real APIs and state; never
recognize its fixtures, fabricate success or hardcode expected responses.

Use task.application_entrypoints for application integration and task.backend_entrypoints
when backend wiring repairs are necessary. Application sources and generated tests are
writable according to tools; original designs and shared test tools remain references.
When startup evidence points into existing database runtime/SQL, repair those files too.
Preserve the declared schema, constraints, previous tables and requirement-defined seed
data; correct their executable implementation rather than removing required guarantees.
Correct a generated test only with original requirement evidence, preserving valid coverage.
The gate compiles and runs current/accepted browser scenarios, affected backend HTTP suites,
UI presence regression and final builds. Return ordinary edit_file calls; no path metadata
or placeholder files for reference trigger IDs are required.

For each failure, diagnose whether it comes from the requirement/test, application,
backend/database startup, wiring, or environment, using actual logs and relevant files.
Server startup, network and browser runtime failures are real repair targets, not invalid
tests or successful RED. Read the failing source and repair its cause within tool scope;
do not weaken assertions, replace real requests with mocks, or relabel failures as passes.
If a necessary correction is outside tool scope, explain the exact blocker in diagnosis.
"""


def run_trigger_tdd(arc_dir, tree, schema, backend, ui, design, images, contexts,
        model, console, report, max_turns=10, max_tests=2):
    """Implement design one requirement at a time through real-app E2E TDD.

    Prepare dependencies/runtime, generate initial key scenario tests, then
    integrate and repair the current requirement before advancing. Regress
    accepted smoke scenarios, build the app, and update the caller's report."""
    output = arc_dir.parent.resolve()
    prepare_frontend(output)
    prepare_e2e(output, backend)
    console.show("E2E preparation | Dependencies", "Install workspace dependencies and Chromium. Each browser run owns a new real test database; production data is not used.")
    install_dependencies(output)
    checks = E2EChecks(output, max_tests)
    checks.install_browser()
    checkpoint(output, stage="12", task="runtime", action="Prepare real-app browser tests and isolated database fixtures",
        details={"pages": list(ui["pages"]), "trigger_ids": list(design["triggers"])})
    accepted, implemented = [], set()
    ui_checks = FrontendChecks(output)
    selection = SourceFiles(output, ui)
    backend_selection = SourceFiles(output, root="backend/src", tests_root="backend/tests")
    context_index = project_index(output,
        kinds=("schema", "api", "page", "ui_element", "ui_data", "trigger", "requirement",
            "test_requirement", "convention", "file"),
        file_roots=("frontend/src", "frontend/tests", "backend/src", "backend/tests"))
    report["status"] = "IMPLEMENTING"
    save_json(arc_dir / "frontend_e2e.json", report)
    baseline_files = [ui_test_path(pid) for pid in ui["pages"]
        if (output / ui_test_path(pid)).is_file()]

    def baseline_gate():
        """Check inherited sources independently of the next business requirement."""
        evidence = {"typecheck": checks.typecheck(baseline_files)}
        try:
            if evidence["typecheck"]["returncode"]:
                raise ValueError(evidence["typecheck"]["output"])
            if baseline_files:
                evidence["ui"] = ui_checks.tests(baseline_files)
                require_green(evidence["ui"])
        except (ValueError, RuntimeError) as error:
            raise TriggerCheckFailure("Application baseline failed: " + str(error), evidence) from error
        return evidence

    report["baseline"] = {"status": "CHECKING"}
    with implementation_task(output, report["baseline"], console, "12 / baseline"):
        try:
            baseline = baseline_gate()
        except (ValueError, RuntimeError) as error:
            workspace = selection.workspace(paths=APPLICATION_ENTRYPOINTS,
                references=["frontend/src/ui-runtime.ts", "frontend/package.json",
                    "frontend/tsconfig.json", "frontend/playwright.ui.config.ts"])
            workspace.allow_write = lambda path: editable_runtime_path(output, path)

            def baseline_feedback(value):
                return selection.feedback(workspace, backend_selection.feedback(workspace, value))

            repair = run_file_agent(model,
                "Restore the existing application's compilation and display behavior before business work. "
                "Read the actual entrypoints and failing sources. Use native framework routing/state/events; "
                "do not recreate a compiler-owned dispatcher, global input capture or design interpreter. "
                "Preserve earlier pages, selectors and behavior. This is a shared baseline repair, not "
                "implementation of all future triggers. Read missing requirement/design evidence on demand. "
                "Shared presentation/test infrastructure is read-only. Repair the actual application.",
                {"task": "application_baseline", "application_entrypoints": list(APPLICATION_ENTRYPOINTS)},
                workspace, baseline_gate, max_turns, console, "Application baseline repair",
                feedback=getattr(error, "feedback", {"error": str(error)}),
                feedback_filter=baseline_feedback, context_index=context_index)
            baseline = repair["checks"]
            report["baseline"]["repair_turns"] = repair["turns"]
        report["baseline"].update(status="GREEN", checks=baseline)
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
        targets = tids
        relative = test_path(rid, output)
        ui_files = [ui_test_path(pid) for pid in pages if (output / ui_test_path(pid)).is_file()]
        called = {aid for trigger in context["triggers"].values() for aid in api_ids(trigger)}
        context["obligations"] = {tid: trigger_obligations(trigger, backend) for tid, trigger in context["triggers"].items()}
        context.update({"requirement": contexts[rid],
            "target_trigger_ids": sorted(targets),
            "backend_apis": {aid: backend["apis"][aid] for aid in sorted(called)}})
        console.show(label + " | Scenario context", json.dumps(context, ensure_ascii=False, indent=2))
        report["requirements"][rid] = {"status": "GENERATING_TESTS", "triggers": sorted(tids),
            "target_triggers": sorted(targets), "test_path": relative}
        save_json(arc_dir / "frontend_e2e.json", report)
        with implementation_task(output, report["requirements"][rid], console, "12 / " + rid):
            regression_files = [test_path(key, output) for key in [*accepted, rid]]

            def generation_checks():
                """Typecheck selected tests; test_gate also runs the real application."""
                nonlocal relative, regression_files
                relative = test_path(rid, output)
                regression_files = [test_path(key, output) for key in [*accepted, rid]]
                return checks.typecheck(regression_files, full_source=False)

            def test_gate():
                """Compile the suite, then preserve real execution failures for implementation repair."""
                compiled = generation_checks()
                if compiled["returncode"]:
                    raise ValueError(compiled["output"])
                try:
                    behavior = checks.tests([relative])
                except (ValueError, RuntimeError) as error:
                    behavior = {"returncode": 1, "output": str(error), "errors": [str(error)]}
                return {"typecheck": compiled, "behavior": behavior, "status": test_run_status(behavior)}

            test_context = {**model_context(context), "schema": related_schema(schema, context["backend_apis"].values()), "test_path": relative if (output / relative).is_file() else None,
                "max_tests": max_tests}
            test_workspace = selection.workspace(target=("e2e_test", rid), existing=relative,
                references=["frontend/src/ui-runtime.ts", CONFIG, FIXTURE, "backend/tests/support/context.ts",
                    *selection.paths("page", pages), *APPLICATION_ENTRYPOINTS,
                    "frontend/package.json", "frontend/tsconfig.json",
                    *backend_selection.paths("api", called),
                    *[f"backend/src/db/tables/{name}.sql" for name in related_schema(schema, context["backend_apis"].values())]])
            agent, generation_feedback = None, None
            if (output / relative).is_file():
                try:
                    agent = {"turns": 0, "checks": test_gate()}
                except (ValueError, RuntimeError) as error:
                    generation_feedback = getattr(error, "feedback", {"error": str(error)})
            if agent is None:
                agent = run_file_agent(model, TEST_INSTRUCTIONS, test_context,
                    test_workspace, test_gate, max_turns, console, label + " / Test Generation",
                    feedback=generation_feedback,
                    feedback_filter=lambda value: selection.feedback(test_workspace, value), context_index=context_index)
            report["requirements"][rid]["test_turns"] = agent["turns"]
            report["requirements"][rid]["test_path"] = relative

            workspace = None

            def implementation_checks():
                """Compile sources and run accepted functional scenarios; regress APIs if edited."""
                compiled = checks.typecheck(regression_files)
                result = {"typecheck": compiled, "e2e": None}
                if compiled["returncode"]:
                    return result
                if workspace and any(path.startswith(("backend/src/", "backend/tests/")) for path in workspace.changed_paths):
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
                if ui_files:
                    result["ui"] = ui_checks.tests(ui_files)
                return result

            def implementation_gate():
                """Require actual implementations, compilation and functional smoke results."""
                result = implementation_checks()
                try:
                    for kind in ("typecheck", "backend_typecheck"):
                        if result.get(kind) and result[kind]["returncode"]:
                            raise ValueError(result[kind]["output"])
                    if "backend_tests" in result:
                        require_backend_green(result["backend_tests"])
                    if test_run_status(result["e2e"]) != "GREEN":
                        raise ValueError("Functional scenarios require passing, unskipped and stable results")
                    if "ui" in result:
                        require_green(result["ui"])
                except ValueError as error:
                    raise TriggerCheckFailure("Functional integration or compilation failed", result) from error
                return result

            generated = agent["checks"]
            current = {"typecheck": generated["typecheck"], "e2e": generated["behavior"]}
            report["requirements"][rid]["status"] = generated["status"]
            save_json(arc_dir / "frontend_e2e.json", report)
            checkpoint(output, stage="12", task=rid, action="Publish functional smoke tests before implementation",
                status=generated["status"], details={"test_path": relative, "checks": generated})
            report["requirements"][rid]["status"] = "IMPLEMENTING"
            task = {**model_context(context),
                "application_entrypoints": list(APPLICATION_ENTRYPOINTS),
                "backend_entrypoints": {"registry": "backend/src/api/register.ts",
                    "app": "backend/src/app.ts", "server": "backend/src/server.ts"}}
            workspace = selection.workspace(paths=[*selection.paths("page", pages), "frontend/src/style.css"],
                references=[relative, *ui_files, "backend/tests/support/context.ts",
                    "frontend/src/ui-runtime.ts", CONFIG, *APPLICATION_ENTRYPOINTS,
                    "frontend/package.json", "frontend/tsconfig.json"])
            workspace.allow_write = lambda path: editable_runtime_path(output, path)
            backend_selection.include(workspace, [*backend_selection.paths("api", called),
                *[path for aid in called if (path := selected_path(output, "backend_test", aid))]])

            def repair_feedback(value):
                return selection.feedback(workspace, backend_selection.feedback(workspace, value))
            agent = None
            if generated["status"] == "GREEN":
                try:
                    agent = {"turns": 0, "checks": implementation_gate()}
                except (ValueError, RuntimeError) as error:
                    current = getattr(error, "feedback", {"error": str(error)})
            if agent is None:
                agent = run_file_agent(model, IMPLEMENT_INSTRUCTIONS, task, workspace,
                    implementation_gate, max_turns, console, label + " / Interaction Implementation",
                    feedback=current, feedback_filter=repair_feedback, context_index=context_index)
            accepted.append(rid)
            reused = tids & implemented
            implemented.update(targets)
            result = agent["checks"]["e2e"]
            report["requirements"][rid].update({"status": "GREEN", "implementation_turns": agent["turns"],
                "steps": list(steps), "passed": result["passed"], "reused_triggers": sorted(reused)})
            save_json(arc_dir / "frontend_e2e.json", report)
            console.show(label + " | GREEN", result["output"])
        save_json(arc_dir / "frontend_e2e.json", report)
    return verify_frontend(arc_dir, tree, backend, ui, console, report)


def verify_frontend(arc_dir, tree, backend, ui, console, report):
    """Check current files again after implementation or independent acceptance repair."""
    output = arc_dir.parent.resolve()
    checks = E2EChecks(output)
    ui_checks = FrontendChecks(output)
    console.show("Final frontend verification", "Run available functional suites, UI regression and both builds against current sources.")
    files = [test_path(rid, output) for rid in tree.leaves
        if report["requirements"].get(rid, {}).get("status") != "NO_TRIGGERS"
        and (output / test_path(rid, output)).is_file()]
    ui_files = [ui_test_path(pid) for pid in ui["pages"] if (output / ui_test_path(pid)).is_file()]
    api_checks = BackendChecks(output)
    api_files = [path for aid in backend["apis"]
        if (path := selected_path(output, "backend_test", aid)) and (output / path).is_file()]
    verification = final_checks(console,
        typecheck=(lambda: checks.typecheck(files), None),
        e2e=(lambda: checks.tests(files), require_green)) if files else final_checks(console,
            typecheck=(lambda: checks.typecheck([]), None))
    if ui_files:
        verification.update(final_checks(console, ui=(lambda: ui_checks.tests(ui_files), require_green)))
    verification.update(final_checks(console,
        backend_typecheck=(api_checks.typecheck, None),
        backend_tests=(lambda: api_checks.tests(api_files), require_backend_green if api_files else None),
        build=(checks.build, None)))
    final = verification.get("e2e", {}).get("result") or {}
    ui_final = verification.get("ui", {}).get("result") or {}
    accepted = [rid for rid in tree.leaves if report["requirements"].get(rid, {}).get("status") == "GREEN"]
    implemented = {tid for rid in accepted for tid in report["requirements"][rid].get("target_triggers", [])}
    report["summary"] = {"requirements": len(accepted), "triggers": len(implemented),
        "e2e_tests": final.get("passed", 0), "ui_tests": ui_final.get("passed", 0),
        "failed": final.get("failed", 0) + ui_final.get("failed", 0)}
    complete_report(report, report["requirements"].values(), verification)
    save_json(arc_dir / "frontend_e2e.json", report)
    return report
