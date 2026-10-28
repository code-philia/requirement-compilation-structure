"""Step 12 orchestration: scenario test generation -> event repair -> regression.

For each leaf requirement, one agent generates key E2E cases and another repairs
the event implementation. Complete that requirement before advancing; include
accepted scenarios and UI presence tests in regression checks."""

import json

from infrastructure.shared.agent.files import FileTools, project_structure
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.stages.backend.context import supplied_sources
from infrastructure.stages.frontend.interactions.e2e_runtime import CONFIG, FIXTURE, RUNNER, VITE_CONFIG, prepare_e2e
from infrastructure.stages.frontend.interactions.testing import E2EChecks, require_behavioral_red, test_path, validate_test_source
from infrastructure.stages.frontend.interactions.runtime import API_CLIENT, EVENT_REGISTRY, PROTECTED, event_module, sync_interactions
from infrastructure.stages.frontend.ui.runtime import prepare_frontend
from infrastructure.stages.frontend.ui.testing import FrontendChecks, assert_frozen, frozen_files, require_green, test_path as ui_test_path
from infrastructure.stages.frontend.interactions.design import api_ids, event_ids, relevant_pages
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import save_json


def page_dependency_context(ui, interactions, pages, owned_events):
    """Collect read-only event context already attached to the pages in a scenario."""
    elements = {uid for page in pages.values() for uid in page["elements"]}
    page_events = {
        trigger["action"]
        for trigger in interactions["triggers"].values()
        if trigger["source"] in elements
    }
    dependency_events = sorted(page_events - set(owned_events))
    return {
        "events": {eid: interactions["events"][eid] for eid in dependency_events},
        "contracts": {eid: interactions["contracts"][eid] for eid in dependency_events},
        "triggers": {
            tid: trigger for tid, trigger in interactions["triggers"].items()
            if trigger["action"] in dependency_events
        },
        "event_ids": dependency_events,
    }

TEST_INSTRUCTIONS = '''Write a few real Playwright E2E tests BEFORE implementation of the current requirement.
Edit only test_path. Import {test,expect,fixturePasswordHash} from ./support/context.js.
Use literal test("title",async ({page,database})=>{...}) calls, at most max_tests total.
The support fixture automatically resets an isolated real SQLite DB before every case.
Seed Given records with parameterized SQL and supplied real table definitions; fixture
passwords use fixturePasswordHash. database is a better-sqlite3 connection, not a mock.
Do not call another API to fabricate Given state. Bind booleans as 0/1. SQL writes are
for Given setup only; after the When action, inspect DB state independently with SELECT.
All When actions go through page.goto/getByTestId/getByRole/fill/check/selectOption/click.
Use real browser requests; do not use page.request, fetch, mocks, route interception,
UI fixture injection, arbitrary filesystem/process code, test skips/only/fail, or exits.
The fixture also rejects application runtime errors and undeclared API response statuses.
Assert visible UI outcomes AND required persistence/forbidden writes. Include success,
meaningful rejection, cross-page navigation, and reload persistence when required.
For dynamic text, use awaited Playwright assertions such as toHaveText, toContainText,
toHaveValue, or toHaveURL. Do not read textContent() and assert its length immediately
after toBeVisible(); elements may exist before React has rendered their updated text.
For alerts, assert the declared message with toHaveText/toContainText rather than only
asserting that an always-mounted alert element is visible.
Do not assume UUIDs, hashes, timestamps or exact wording not specified by contracts.
Use expect assertions on UI results before inspecting network observations. Missing
interactions must fail by assertion, not by an unbounded waitForResponse or a test timeout.
Use Playwright's retrying assertions for every asynchronous UI result: toHaveText,
toContainText, toHaveValue, toBeChecked, toHaveURL, and locator state assertions.
Never use textContent(), innerHTML(), waitForTimeout(), or a synchronous length check
after toBeVisible(). An alert may be permanently mounted with an empty placeholder;
assert its declared message with toHaveText/toContainText.
Observe network through page.on('response') or expect.poll when needed, not direct API calls.
One case can trace many steps/events. Every required STEP:ID and EVENT:ID supplied in
trace_tokens must appear in actual literal test titles, separated by spaces. Do not
put coverage labels only in comments. Group field assertions in a few scenario tests;
never create one test per input variation or local input event. Only claim conditions
exercised by the case. P/Q and API status branches inform scenarios, but unreachable
technical branches do not justify fake responses or bypassing the UI. Cover ALL supplied
requirement steps and newly introduced events through the relevant complete workflows.
Use actual UI IDs, exact API fields and database schema. Remember response.body is unknown
in helper APIs; use appropriate casts for SQL rows and captured response objects.
Only the generated test file is editable. The compiler owns fixtures, app startup,
database reset and test commands. The generation gate checks traceability, TypeScript,
and executable scenarios against the current application. Assertion RED is accepted;
invalid locators, fixture/runtime errors, and timeouts need test repair, not skipped tests.
'''

IMPLEMENT_INSTRUCTIONS = '''Implement the current requirement's designed UI interactions against frozen E2E tests.
Use only the supplied UI/data, trigger/event actions, contracts and canonical backend APIs.
Page dependencies are supplied for understanding complete workflows; preserve them and
implement only the selected event_module_ids for the current requirement.
The compiler captures DOM click/change/input/submit/keyboard events and page mount, owns
central frontend data, and directly imports the named event functions you register.
Export one function per selected event with signature
(context: UiEventContext) => void | Promise<void>, importing the type from ui-runtime.
Choose source filenames and helper modules under frontend/src. Use edit_files with
entrypoints:{"frontend:event:EVENT-ID":{"path":"your/source.ts","export":"yourFunction"},...}
for the supplied module IDs. Several functions may share a file. Keep existing page
entrypoints; the compiler owns App.tsx, ui-runtime.ts, ui-events.ts, ui-api.ts and routing.
UiEventContext provides:
- data: latest readonly frontend variable values, keyed by the designed var strings;
- input: native value (string), checked (boolean), key (string) as appropriate;
- trigger: id/source/event/guard, so shared handlers can implement their enabling rules;
- update({var:value,...}): update only the event's declared frontend writes;
- api(apiId,{params,query,body,headers,credentials}): real canonical HTTP call returning
  {status,body:unknown,headers}. Use designed request mappings and same-origin/include
  credentials; browser cookies are automatic, never manually read or stored;
- navigate(pageId): navigate to the event's declared target page.
Implement guard/P, ordered actions, local validation, value transformations, status/error
branches, frontend Q and navigation. Read native changes from input and persist them
with update. Convert number inputs explicitly. Do not normalize exact-match usernames.
Do not store plaintext credentials or session tokens outside transient designed data.
All API access must use context.api, not alternate endpoints, direct DB access or fake
responses. Preserve failure-without-writes and existing state. Do not swallow errors or
hardcode fixture credentials. Handler modules must have no top-level business effects.
The compiler automatically suppresses business events for step 10 display fixtures;
never detect tests or inspect fixture globals in your implementation. Page components
should remain presentation-only. You may repair their data rendering while preserving
UI IDs, semantics and Tailwind styles, but do not attach duplicate event handlers/hooks.
Frozen backend, SQL, designs, fixtures, tests and compiler infrastructure cannot change.
Run checks, inspect real browser/DB feedback and iterate until current AND previously
accepted requirements and all UI existence tests pass. Missing required entrypoints
still prevent acceptance even if an inadequate current implementation appears to pass.
'''


def run_interaction_tdd(arc_dir, tree, schema, backend, ui, interactions, images, contexts, index,
        model, console, report, max_turns=18, max_tests=5):
    """Implement interactions one requirement at a time through real-app E2E TDD.

    Prepare dependencies/runtime, generate and freeze key scenario tests, then
    activate and repair the current event handlers before advancing. Regress
    accepted E2E/UI tests, build the app, and update the caller's report."""
    output = arc_dir.parent.resolve()
    prepare_frontend(output, index)
    prepare_e2e(output, backend, index)
    sync_interactions(output, ui, interactions, backend, index, [])
    console.show("E2E preparation | Dependencies", "Install workspace dependencies and Chromium. Each browser run owns a new real test database; production data is not used.")
    install_dependencies(output)
    checks, ui_checks = E2EChecks(output, max_tests), FrontendChecks(output)
    checks.install_browser()
    ui_files = [ui_test_path(pid) for pid in ui["pages"]]
    immutable = [".arc/ui_design.json", ".arc/ui_interactions.json", ".arc/backend_contracts.json",
        CONFIG, FIXTURE, RUNNER, VITE_CONFIG, API_CLIENT, "frontend/src/ui-runtime.ts",
        "frontend/src/main.tsx", "frontend/src/style.css", "frontend/vite.config.ts", "frontend/tsconfig.json",
        "frontend/package.json", "package.json", *ui_files]
    immutable.extend(path.relative_to(output).as_posix() for path in (output / "backend").rglob("*")
        if path.is_file() and "node_modules" not in path.parts and "dist" not in path.parts and "data" not in path.relative_to(output / "backend").parts)
    frozen = frozen_files(output, immutable)
    baseline = ui_checks.tests(ui_files)
    require_green(baseline)
    accepted, implemented = [], set()
    report["status"] = "IMPLEMENTING"
    save_json(arc_dir / "frontend_e2e.json", report)
    for number, rid in enumerate(tree.leaves, 1):
        tids = interactions["requirements"][rid]
        eids = event_ids(interactions, tids)
        new_events = sorted(eids - implemented)
        steps = tree.own_steps[rid]
        label = f"E2E requirement {number}/{len(tree.leaves)} {rid}"
        if not eids and not steps:
            report["requirements"][rid] = {"status": "NO_INTERACTIONS", "events": []}
            save_json(arc_dir / "frontend_e2e.json", report)
            continue
        active = implemented | eids
        relative = test_path(rid)
        selected = {eid: interactions["events"][eid] for eid in sorted(eids)}
        contracts = {eid: interactions["contracts"][eid] for eid in sorted(eids)}
        pages = relevant_pages(ui, rid)
        dependencies = page_dependency_context(ui, interactions, pages, eids)
        console.show(label + " | Requirement / UI / event contracts", json.dumps({"requirement": contexts[rid],
            "pages": list(pages), "new_events": new_events, "events": selected, "contracts": contracts,
            "page_dependencies": dependencies}, ensure_ascii=False, indent=2))
        report["requirements"][rid] = {"status": "GENERATING_TESTS", "events": sorted(eids), "test_path": relative}
        save_json(arc_dir / "frontend_e2e.json", report)
        regression_files = [test_path(key) for key in [*accepted, rid]]
        sync_interactions(output, ui, interactions, backend, index, implemented)

        def generation_checks():
            """Verify frozen files and typecheck selected tests; test_gate adds source and real-app behavior validation."""
            assert_frozen(output, frozen)
            return checks.typecheck([*regression_files, *ui_files], full_source=False)

        def test_gate():
            """Accept generated tests only when their structure and compilation pass; allow behavioral RED before implementation."""
            validate_test_source((output / relative).read_text(), steps, new_events, max_tests)
            compiled = generation_checks()
            if compiled["returncode"]:
                raise ValueError(compiled["output"])
            behavior = checks.tests([relative])
            if behavior["returncode"]:
                require_behavioral_red(behavior)
            else:
                require_green(behavior)
            return {"typecheck": compiled, "behavior": behavior}

        called = {aid for event in selected.values() for aid in api_ids(event)}
        sources = {FIXTURE: (output / FIXTURE).read_text()}
        for aid in called:
            sources.update(supplied_sources(output, backend["apis"][aid], schema))
        test_context = {"requirement": contexts[rid], "page_subtrees": pages,
            "events": selected, "contracts": contracts, "backend_apis": {aid: backend["apis"][aid] for aid in sorted(called)},
            "page_dependencies": dependencies,
            "schema": schema, "test_path": relative, "max_tests": max_tests,
            "trace_tokens": [*(f"STEP:{sid}" for sid in steps), *(f"EVENT:{eid}" for eid in new_events)], "source_files": sources}
        agent = run_file_agent(model, TEST_INSTRUCTIONS, test_context,
            FileTools(output, {relative}, generation_checks, index=index, requirements=[rid], module=f"tests:e2e:{rid}"),
            test_gate, max_turns, console, label + " / Test Generation")
        index.record([relative], [rid], f"tests:e2e:{rid}")
        report["requirements"][rid]["test_turns"] = agent["turns"]
        frozen.update(frozen_files(output, [relative]))

        def implementation_checks():
            """Refresh active event registrations, verify frozen files, and execute compilation, accepted E2E, and UI regression checks."""
            assert_frozen(output, frozen)
            sync_interactions(output, ui, interactions, backend, index, active)
            compiled = checks.typecheck([*regression_files, *ui_files])
            if compiled["returncode"]:
                return {"typecheck": compiled, "e2e": None, "ui": None}
            tested = checks.tests(regression_files)
            assert_frozen(output, frozen)
            presence = ui_checks.tests(ui_files) if tested["returncode"] == 0 else None
            assert_frozen(output, frozen)
            return {"typecheck": compiled, "e2e": tested, "ui": presence}

        def implementation_gate():
            """Accept current event handlers only after compilation and all required browser regressions pass."""
            missing = [eid for eid in eids if event_module(eid) not in index.data["entrypoints"]]
            if missing:
                raise ValueError(f"Register all current event functions using edit_files.entrypoints: {missing}")
            result = implementation_checks()
            if result["typecheck"]["returncode"]:
                raise ValueError(result["typecheck"]["output"])
            require_green(result["e2e"])
            require_green(result["ui"])
            return result

        current = implementation_checks()
        if current["e2e"] is not None and current["e2e"]["returncode"]:
            errors = current["e2e"].get("failures", [])
            runtime_repair = any("E2E_RUNTIME_ERROR:" in error.split("\n", 1)[0] for error in errors)
            infrastructure_error = current["e2e"].get("errors") or any(
                "E2E_BACKEND_ERROR:" in error.split("\n", 1)[0] or "E2E_NETWORK_ERROR:" in error.split("\n", 1)[0] for error in errors)
            if runtime_repair and not infrastructure_error:
                report["requirements"][rid]["status"] = "REPAIR_REQUIRED"
                console.show(label + " | Repair existing frontend runtime failure", current["e2e"]["output"])
            else:
                require_behavioral_red(current["e2e"])
                report["requirements"][rid]["status"] = "RED_CONFIRMED"
                console.show(label + " | RED: interaction assertions fail", current["e2e"]["output"])
        else:
            report["requirements"][rid]["status"] = "CHECKING_OR_REPAIRING"
        save_json(arc_dir / "frontend_e2e.json", report)
        if current["e2e"] and current["e2e"]["returncode"] == 0 and current["ui"] and current["ui"]["returncode"] == 0 and all(event_module(eid) in index.data["entrypoints"] for eid in eids):
            require_green(current["e2e"])
            require_green(current["ui"])
            agent = {"turns": 0, "checks": current}
        else:
            dependency_files = sorted({
                path for eid in dependencies["event_ids"]
                for path in index.files_for(module=event_module(eid))
            })
            context = {"requirement": contexts[rid], "page_subtrees": pages, "events": selected,
                "contracts": contracts, "triggers": {tid: interactions["triggers"][tid] for tid in tids},
                "page_dependencies": dependencies,
                "event_module_ids": {eid: event_module(eid) for eid in sorted(eids)},
                "backend_apis": {aid: backend["apis"][aid] for aid in sorted(called)},
                "frozen_tests": {path: (output / path).read_text() for path in regression_files},
                "project_structure": project_structure(output, "frontend"), "initial_feedback": current}
            agent = run_file_agent(model, IMPLEMENT_INSTRUCTIONS, context,
                FileTools(output, None, implementation_checks, roots=("frontend/src",), read_roots=("frontend",),
                    context_files=("frontend/src/ui-runtime.ts", API_CLIENT, EVENT_REGISTRY, "frontend/src/App.tsx", "frontend/package.json", *dependency_files),
                    protected=PROTECTED, index=index, requirements=[rid], module=f"frontend:requirement:{rid}",
                    entrypoint_modules=[event_module(eid) for eid in eids]),
                implementation_gate, max_turns, console, label + " / Interaction Implementation")
        accepted.append(rid)
        implemented.update(eids)
        result = agent["checks"]["e2e"]
        report["requirements"][rid].update({"status": "GREEN", "implementation_turns": agent["turns"],
            "steps": list(steps), "passed": result["passed"], "reused_events": sorted(eids - set(new_events))})
        save_json(arc_dir / "frontend_e2e.json", report)
        console.show(label + " | GREEN", result["output"])
    sync_interactions(output, ui, interactions, backend, index, implemented)
    console.show("Final frontend verification", "Run every generated E2E scenario and UI existence suite, then build the full application.")
    current_tests = {test_path(rid) for rid in accepted}
    retired = {path for module, paths in index.data["modules"].items() if module.startswith("tests:e2e:")
        for path in paths if path not in current_tests and path.endswith(".spec.ts")
        and (output / path).resolve().is_relative_to(output / "frontend/tests/e2e")}
    if retired:
        index.forget_files(retired)
        for relative in retired:
            (output / relative).unlink(missing_ok=True)
    final = checks.tests([test_path(rid) for rid in accepted]) if accepted else None
    if final is not None:
        require_green(final)
    presence = ui_checks.tests(ui_files)
    require_green(presence)
    built = checks.build()
    if built["returncode"]:
        raise ValueError(built["output"])
    assert_frozen(output, frozen)
    report.update({"status": "GREEN", "summary": {"requirements": len(accepted), "events": len(implemented),
        "e2e_tests": final["passed"] if final else 0, "ui_tests": presence["passed"], "failed": 0}})
    save_json(arc_dir / "frontend_e2e.json", report)
    return report
