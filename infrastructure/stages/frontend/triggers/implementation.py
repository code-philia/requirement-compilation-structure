"""Step 12 orchestration: scenario test generation -> trigger repair -> regression.

For each leaf requirement, one agent generates key E2E cases and another repairs
the trigger implementation. Complete that requirement before advancing; include
accepted scenarios and UI presence tests in regression checks."""

import json

from infrastructure.shared.agent.files import source_paths
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.stages.frontend.triggers.e2e_runtime import FIXTURE, prepare_e2e
from infrastructure.stages.frontend.triggers.testing import E2EChecks, require_behavioral_red, test_path
from infrastructure.stages.frontend.triggers.runtime import sync_triggers
from infrastructure.stages.frontend.ui.runtime import prepare_frontend
from infrastructure.stages.frontend.ui.testing import FrontendChecks, require_green, test_path as ui_test_path
from infrastructure.stages.frontend.triggers.design import api_ids, trigger_obligations, relevant_pages
from infrastructure.stages.frontend.triggers.scope import TriggerCheckFailure, TriggerFiles, model_context
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


TEST_INSTRUCTIONS = '''Write a few real Playwright E2E tests BEFORE implementation of the current requirement.
For a new suite, choose a .spec.ts path under task.new_file.directory; otherwise edit test_path.
Import {test,expect,fixturePasswordHash} from frontend/tests/e2e/support/context.ts,
using the correct relative .js import from your chosen file path.
Use literal test("title",async ({page,database})=>{...}) calls, at most max_tests total.
The support fixture automatically resets an isolated real SQLite DB before every case.
Seed Given records with parameterized SQL and supplied real table definitions; fixture
passwords use fixturePasswordHash. database is a better-sqlite3 connection, not a mock.
Do not call another API to fabricate Given state. Bind booleans as 0/1. SQL writes are
for Given setup only; after the When action, inspect DB state independently with SELECT.
All When actions go through page.goto/getByTestId/getByRole/fill/check/selectOption/click.
Use real browser requests; do not use page.request, fetch, mocks, route interception,
UI fixture injection, arbitrary filesystem/process code, test skips/only/fail, or exits.
The fixture reports actual browser runtime and network errors.
Assert visible UI outcomes AND required persistence/forbidden writes. Include success,
meaningful rejection, cross-page navigation, and reload persistence when required.
For dynamic text, use awaited Playwright assertions such as toHaveText, toContainText,
toHaveValue, or toHaveURL. Do not read textContent() and assert its length immediately
after toBeVisible(); elements may exist before React has rendered their updated text.
For alerts, assert the declared message with toHaveText/toContainText rather than only
asserting that an always-mounted alert element is visible.
Do not assume UUIDs, hashes, timestamps or exact wording not specified by contracts.
Use expect assertions on UI results before inspecting network observations. Missing
design must fail by assertion, not by an unbounded waitForResponse or a test timeout.
Use Playwright's retrying assertions for every asynchronous UI result: toHaveText,
toContainText, toHaveValue, toBeChecked, toHaveURL, and locator state assertions.
Never use textContent(), innerHTML(), waitForTimeout(), or a synchronous length check
after toBeVisible(). An alert may be permanently mounted with an empty placeholder;
assert its declared message with toHaveText/toContainText.
Observe network through page.on('response') or expect.poll when needed, not direct API calls.
Use readable scenario titles and cover requirement behavior through UI and database
assertions. Keep a few meaningful workflows rather than a separate case for every input.
Use actual UI IDs, exact API fields and database schema. Remember response.body is unknown
in helper APIs; use appropriate casts for SQL rows and captured response objects.
The current test and supplied writable frontend sources are editable. Failed checks
automatically supply the affected source files and their local dependencies. If compilation
or execution fails in an existing page or handler, repair that source directly rather
than repeatedly rewriting an unrelated test. Write tests first; do not implement new
trigger implementations before their tests. Preserve existing behavior, UI IDs, contracts and
already accepted scenarios. Read-only source files and other tests remain references.
Do not redeclare compiler-owned runtime types inside page or test modules.
The compiler owns fixtures, app startup,
database reset and test commands. The generation gate checks TypeScript,
and executable scenarios against the current application. Assertion RED is accepted;
invalid locators, fixture/runtime errors, and timeouts need test repair, not skipped tests.
'''

IMPLEMENT_INSTRUCTIONS = '''Implement the current requirement's designed UI design against E2E tests.
Use the supplied requirement, UI/data, trigger guards, frontend read/write sets and ordered actions, plus canonical backend APIs.
During creation, the context describes one trigger. During requirement repair it describes
all required triggers, including destination-page lifecycle behavior. Preserve other handlers' behavior.
Use supplied implementation_paths and page IDs. When task.new_file is supplied,
choose a source path for that target and create it in the first edit. Other missing
handlers are implemented in subsequent calls; do not create their files in this call.
The compiler captures DOM click/change/input/submit/keyboard events and page mount, owns
central frontend data, and imports each trigger's fixed handle export.
Export handle with signature (context: UiTriggerContext) => void | Promise<void>,
importing its type from ui-runtime. Use one source file per trigger.
The compiler owns App.tsx, ui-runtime.ts, ui-triggers.ts, ui-api.ts and routing.
Return complete file contents in edits; the compiler remembers the selected path and registers it.
UiTriggerContext provides:
- data: latest readonly frontend variable values, keyed by the designed var strings;
- input: native value (string), checked (boolean), key (string) as appropriate;
- trigger: id/source/event, so shared handlers can implement their enabling rules;
- update({var:value,...}): update only the trigger's frontend data;
- api(apiId,{params,query,body,headers,credentials}): real canonical HTTP call returning
  {status,body:unknown,headers}. Follow action descriptions and fixed API schemas; use same-origin/include
  credentials; browser cookies are automatic, never manually read or stored;
- navigate(pageId): navigate to the target page.
Implement the guard, ordered actions, value transformations, status/error branches
and navigation. UI input values are synchronized before business triggers run.
The derived DB obligations describe API effects; connect UI data to API requests
and API responses to UI data in ordinary code. Convert number inputs explicitly. Do not normalize exact-match usernames.
Do not store plaintext credentials or session tokens outside transient designed data.
All API access must use context.api, not alternate endpoints, direct DB access or fake
responses. Preserve failure-without-writes and existing state. Do not swallow errors or
hardcode fixture credentials. Handler modules must have no top-level business effects.
The compiler automatically suppresses business events for step 10 display fixtures;
never detect tests or inspect fixture globals in your implementation. Page components
should remain presentation-only. Any supplied writable frontend source may be repaired; preserve
UI IDs, semantics and Tailwind styles, but do not attach duplicate event handlers/hooks.
Frozen backend, SQL, designs, fixtures, tests and compiler infrastructure cannot change.
Creation checks compilation; a separate requirement repair phase runs all behavior checks.
Failed checks automatically supply affected sources and their local imports for repair.
Inspect automatic browser/DB check feedback and iterate until current AND previously
accepted requirements and all UI existence tests pass. 
'''


def run_trigger_tdd(arc_dir, tree, schema, backend, ui, design, images, contexts,
        model, console, report, max_turns=18, max_tests=5):
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
    selection = TriggerFiles(output, ui)
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
            references=[FIXTURE, *source_paths(output, "backend/src/db")])
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

        current = implementation_checks()
        report["requirements"][rid]["status"] = test_run_status(current["e2e"]) if current["e2e"] is not None else "REPAIR_REQUIRED"
        save_json(arc_dir / "frontend_e2e.json", report)
        missing = [tid for tid in sorted(targets)
            if not (path := selected_path(output, "trigger", tid)) or not (output / path).is_file()]
        if not missing and current["e2e"] and current["e2e"]["returncode"] == 0 and current["ui"] and current["ui"]["returncode"] == 0:
            require_green(current["e2e"])
            require_green(current["ui"])
            agent = {"turns": 0, "checks": current}
        else:
            total_turns = 0
            # Keep the complete target set, including cross-page dependencies.
            # Each creation request sees only its own trigger and actual imports.
            for new_trigger in missing:
                task = {**model_context(context, {new_trigger}),
                    "implementation_paths": {new_trigger: selected_path(output, "trigger", new_trigger)}}
                workspace = selection.workspace(target=("trigger", new_trigger))

                def creation_gate():
                    sync_triggers(output, ui, design, backend, active)
                    compiled = checks.typecheck([*regression_files, *ui_files])
                    if compiled["returncode"]:
                        raise ValueError(compiled["output"])
                    return {"typecheck": compiled}

                agent = run_file_agent(model, IMPLEMENT_INSTRUCTIONS, task, workspace,
                    creation_gate, max_turns, console, label + f" / Create {new_trigger}",
                    feedback_filter=lambda value: selection.feedback(workspace, value))
                total_turns += agent["turns"]

            # Behavioral acceptance belongs to the whole requirement. Every
            # target remains writable, even when it already existed on resume.
            try:
                agent = {"checks": implementation_gate()}
            except ValueError as error:
                console.show(label + " | Requirement repair", str(error))
                task = {**model_context(context),
                    "implementation_paths": {tid: selected_path(output, "trigger", tid) for tid in sorted(targets)}}
                workspace = selection.workspace(triggers=context_tids, references=[relative])
                agent = run_file_agent(model, IMPLEMENT_INSTRUCTIONS, task, workspace,
                    implementation_gate, max_turns, console, label + " / Interaction Implementation",
                    feedback=getattr(error, "feedback", {"error": str(error)}),
                    feedback_filter=lambda value: selection.feedback(workspace, value))
                total_turns += agent["turns"]
            agent["turns"] = total_turns
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
