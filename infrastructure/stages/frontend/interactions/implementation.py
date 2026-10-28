"""Step 12 orchestration: scenario test generation -> event repair -> regression.

For each leaf requirement, one agent generates key E2E cases and another repairs
the event implementation. Complete that requirement before advancing; include
accepted scenarios and UI presence tests in regression checks."""

import json

from infrastructure.shared.agent.files import FileWorkspace, source_paths
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.project.entrypoints import implementation_path, implementation_entrypoint
from infrastructure.stages.frontend.interactions.e2e_runtime import CONFIG, FIXTURE, RUNNER, VITE_CONFIG, prepare_e2e
from infrastructure.stages.frontend.interactions.testing import E2EChecks, require_behavioral_red, test_path, validate_test_source
from infrastructure.stages.frontend.interactions.runtime import API_CLIENT, EVENT_REGISTRY, sync_interactions
from infrastructure.stages.frontend.ui.runtime import prepare_frontend
from infrastructure.stages.frontend.ui.testing import FrontendChecks, check_presentation, assert_frozen, frozen_files, require_green, test_path as ui_test_path
from infrastructure.stages.frontend.interactions.design import api_ids, event_ids, relevant_pages
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import save_json
from infrastructure.stages.frontend.ui.design import page_context, page_elements


def scenario_context(ui, interactions, rid):
    """Include current pages and reachable navigation pages, with each interaction exactly once."""
    pages = set(relevant_pages(ui, rid))
    while True:
        elements = {uid for pid in pages for uid in page_elements(ui, pid)}
        tids = {tid for tid, trigger in interactions["triggers"].items() if trigger["source"] in elements}
        eids = event_ids(interactions, tids)
        destinations = {action["page"] for eid in eids for action in interactions["events"][eid]["actions"] if action["kind"] == "navigate"}
        hrefs = {ui["elements"][uid]["prop"].get("href") for uid in elements}
        destinations.update(pid for pid, page in ui["pages"].items() if page["route"] in hrefs)
        if destinations.issubset(pages):
            return {"page_subtrees": {pid: page_context(ui, pid) for pid in sorted(pages)},
                "triggers": {tid: interactions["triggers"][tid] for tid in sorted(tids)},
                "events": {eid: interactions["events"][eid] for eid in sorted(eids)},
                "contracts": {eid: interactions["contracts"][eid] for eid in sorted(eids)}}
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
One case can trace many steps. Every required STEP:ID supplied in
trace_tokens must appear in actual literal test titles, separated by spaces. Do not
put coverage labels only in comments. Group field assertions in a few scenario tests;
never create one test per input variation or local input event. Only claim conditions
exercised by the case. P/Q and API status branches inform scenarios, but unreachable
technical branches do not justify fake responses or bypassing the UI. Cover ALL supplied
requirement steps through the relevant complete workflows.
Use actual UI IDs, exact API fields and database schema. Remember response.body is unknown
in helper APIs; use appropriate casts for SQL rows and captured response objects.
Only the generated test file is editable. The compiler owns fixtures, app startup,
database reset and test commands. The generation gate checks traceability, TypeScript,
and executable scenarios against the current application. Assertion RED is accepted;
invalid locators, fixture/runtime errors, and timeouts need test repair, not skipped tests.
'''

IMPLEMENT_INSTRUCTIONS = '''Implement the current requirement's designed UI interactions against frozen E2E tests.
Use only the supplied UI/data, trigger/event actions, contracts and canonical backend APIs.
The context contains each scenario interaction once, including destination-page lifecycle
behavior. target_event_ids selects the handlers to implement; preserve all other handlers.
Use only the supplied implementation_paths and page_paths.
The compiler captures DOM click/change/input/submit/keyboard events and page mount, owns
central frontend data, and imports each event's fixed handle export.
Export handle with signature (context: UiEventContext) => void | Promise<void>,
importing its type from ui-runtime. Use one fixed file per event in implementation_paths.
The compiler owns App.tsx, ui-runtime.ts, ui-events.ts, ui-api.ts and routing.
Return complete file contents in edits; do not choose paths or register entrypoints.
UiEventContext provides:
- data: latest readonly frontend variable values, keyed by the designed var strings;
- input: native value (string), checked (boolean), key (string) as appropriate;
- trigger: id/source/event, so shared handlers can implement their enabling rules;
- update({var:value,...}): update only the event's declared frontend writes;
- api(apiId,{params,query,body,headers,credentials}): real canonical HTTP call returning
  {status,body:unknown,headers}. Follow action descriptions and fixed API schemas; use same-origin/include
  credentials; browser cookies are automatic, never manually read or stored;
- navigate(pageId): navigate to the event's declared target page.
Implement semantic P, ordered actions, local validation, value transformations, status/error
branches, frontend Q and navigation. Read native changes from input and persist them
with update. Convert number inputs explicitly. Do not normalize exact-match usernames.
Do not store plaintext credentials or session tokens outside transient designed data.
All API access must use context.api, not alternate endpoints, direct DB access or fake
responses. Preserve failure-without-writes and existing state. Do not swallow errors or
hardcode fixture credentials. Handler modules must have no top-level business effects.
The compiler automatically suppresses business events for step 10 display fixtures;
never detect tests or inspect fixture globals in your implementation. Page components
should remain presentation-only. Only supplied page_paths are writable for data-rendering repair; preserve
UI IDs, semantics and Tailwind styles, but do not attach duplicate event handlers/hooks.
Frozen backend, SQL, designs, fixtures, tests and compiler infrastructure cannot change.
Inspect automatic browser/DB check feedback and iterate until current AND previously
accepted requirements and all UI existence tests pass. Missing required implementation files
still prevent acceptance even if an inadequate current implementation appears to pass.
'''


def run_interaction_tdd(arc_dir, tree, schema, backend, ui, interactions, images, contexts,
        model, console, report, max_turns=18, max_tests=5):
    """Implement interactions one requirement at a time through real-app E2E TDD.

    Prepare dependencies/runtime, generate and freeze key scenario tests, then
    activate and repair the current event handlers before advancing. Regress
    accepted E2E/UI tests, build the app, and update the caller's report."""
    output = arc_dir.parent.resolve()
    prepare_frontend(output)
    prepare_e2e(output, backend)
    sync_interactions(output, ui, interactions, backend, [])
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
        steps = tree.own_steps[rid]
        label = f"E2E requirement {number}/{len(tree.leaves)} {rid}"
        context = scenario_context(ui, interactions, rid)
        pages = context["page_subtrees"]
        if not pages and not eids:
            report["requirements"][rid] = {"status": "NO_INTERACTIONS", "events": []}
            save_json(arc_dir / "frontend_e2e.json", report)
            continue
        context_eids = set(context["events"])
        targets = eids | (context_eids - implemented)
        active = implemented | context_eids
        relative = test_path(rid)
        called = {aid for event in context["events"].values() for aid in api_ids(event)}
        context.update({"requirement": contexts[rid], "target_event_ids": sorted(targets),
            "backend_apis": {aid: backend["apis"][aid] for aid in sorted(called)}})
        console.show(label + " | Scenario context", json.dumps(context, ensure_ascii=False, indent=2))
        report["requirements"][rid] = {"status": "GENERATING_TESTS", "events": sorted(eids),
            "target_events": sorted(targets), "test_path": relative}
        save_json(arc_dir / "frontend_e2e.json", report)
        regression_files = [test_path(key) for key in [*accepted, rid]]
        sync_interactions(output, ui, interactions, backend, active)

        def generation_checks():
            """Verify frozen files and typecheck selected tests; test_gate adds source and real-app behavior validation."""
            assert_frozen(output, frozen)
            return checks.typecheck([*regression_files, *ui_files], full_source=False)

        def test_gate():
            """Accept generated tests only when their structure and compilation pass; allow behavioral RED before implementation."""
            validate_test_source((output / relative).read_text(encoding="utf-8-sig"), steps, max_tests)
            compiled = generation_checks()
            if compiled["returncode"]:
                raise ValueError(compiled["output"])
            behavior = checks.tests([relative])
            status = test_run_status(behavior)
            return {"typecheck": compiled, "behavior": behavior, "status": status}

        test_context = {**context, "schema": schema["entities"], "test_path": relative,
            "max_tests": max_tests, "trace_tokens": [f"STEP:{sid}" for sid in steps]}
        agent = run_file_agent(model, TEST_INSTRUCTIONS, test_context,
            FileWorkspace(output, {relative}, references=[FIXTURE, *source_paths(output, "backend/src/db")]),
            test_gate, max_turns, console, label + " / Test Generation")
        report["requirements"][rid]["test_turns"] = agent["turns"]
        frozen.update(frozen_files(output, [relative]))

        def implementation_checks():
            """Refresh active event registrations, verify frozen files, and execute compilation, accepted E2E, and UI regression checks."""
            assert_frozen(output, frozen)
            sync_interactions(output, ui, interactions, backend, active)
            compiled = checks.typecheck([*regression_files, *ui_files])
            if compiled["returncode"]:
                return {"typecheck": compiled, "presentation": None, "e2e": None, "ui": None}
            presentation = check_presentation(output, checks, ui["pages"])
            if presentation["returncode"]:
                return {"typecheck": compiled, "presentation": presentation, "e2e": None, "ui": None}
            tested = checks.tests(regression_files)
            assert_frozen(output, frozen)
            presence = ui_checks.tests(ui_files) if tested["returncode"] == 0 else None
            assert_frozen(output, frozen)
            return {"typecheck": compiled, "presentation": presentation, "e2e": tested, "ui": presence}

        def implementation_gate():
            """Accept current event handlers only after compilation and all required browser regressions pass."""
            missing = [eid for eid in targets if not implementation_entrypoint(output, "event", eid)]
            if missing:
                raise ValueError(f"Create all current event files with the handle export: {missing}")
            result = implementation_checks()
            for kind in ("typecheck", "presentation"):
                if result[kind] and result[kind]["returncode"]:
                    raise ValueError(result[kind]["output"])
            require_green(result["e2e"])
            require_green(result["ui"])
            return result

        current = implementation_checks()
        report["requirements"][rid]["status"] = test_run_status(current["e2e"]) if current["e2e"] is not None else "REPAIR_REQUIRED"
        save_json(arc_dir / "frontend_e2e.json", report)
        if current["e2e"] and current["e2e"]["returncode"] == 0 and current["ui"] and current["ui"]["returncode"] == 0 and all(implementation_entrypoint(output, "event", eid) for eid in targets):
            require_green(current["e2e"])
            require_green(current["ui"])
            agent = {"turns": 0, "checks": current}
        else:
            event_paths = {eid: implementation_path("event", eid) for eid in sorted(targets)}
            page_paths = {pid: implementation_path("page", pid) for pid in pages}
            task = {**context, "implementation_paths": event_paths, "page_paths": page_paths}
            agent = run_file_agent(model, IMPLEMENT_INSTRUCTIONS, task,
                FileWorkspace(output, set(event_paths.values()) | set(page_paths.values()),
                    references=source_paths(output, "frontend/src") + regression_files + ui_files +
                        ["frontend/package.json", "frontend/tsconfig.json"]),
                implementation_gate, max_turns, console, label + " / Interaction Implementation", feedback=current)
        accepted.append(rid)
        reused = eids & implemented
        implemented.update(targets)
        result = agent["checks"]["e2e"]
        report["requirements"][rid].update({"status": "GREEN", "implementation_turns": agent["turns"],
            "steps": list(steps), "passed": result["passed"], "reused_events": sorted(reused)})
        save_json(arc_dir / "frontend_e2e.json", report)
        console.show(label + " | GREEN", result["output"])
    sync_interactions(output, ui, interactions, backend, implemented)
    console.show("Final frontend verification", "Run every generated E2E scenario and UI existence suite, then build the full application.")
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
