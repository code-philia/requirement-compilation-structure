"""Step 06: implement backend APIs against real-server HTTP acceptance suites."""

import json
from pathlib import Path

from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.recovery import implementation_task, final_checks, complete_report
from infrastructure.stages.backend.context import load_context, requirement_context, supplied_sources, related_schema
from infrastructure.utils.files import read_artifact
from infrastructure.stages.backend.runtime import REGISTER_PATH, TEST_RUNNER_PATH, TEST_SUPPORT_PATH, prepare_runtime, test_path
from infrastructure.stages.backend.testing import BackendChecks, require_green, test_run_status
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import save_json
from infrastructure.shared.project.git import checkpoint


TEST_INSTRUCTIONS = """Write one HTTP acceptance suite for task.api before implementing it.
Derive expected outcomes from the requirement scenarios, API method/path, I/O, P/Q and DB
changes. Use edit_file to create the .test.ts target under backend/tests or update test_path.
Use { test } from node:test and assert from node:assert/strict with async test callbacks.
Import { createApiTest, fixturePasswordHash } as needed from task.support_module with a
relative .js ESM path. Do not import handlers, createApp, server or test aliases.

At the start of each test call const { database, baseURL } = createApiTest(t).
The compiler owns a real backend process running backend/src/server.ts, its assigned port
and its temporary on-disk database. The helper restores prerequisite data before each case
and opens that SAME database for Given setup and SQL observations. Test files/cases run
sequentially. Do not start a server, choose a port, create a separate database, run tests
concurrently, mock HTTP or call business functions directly.

Exercise EVERY success/rejection case through real HTTP:
const response = await fetch(new URL('/api/example', baseURL), {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ example: 'value' }), redirect: 'manual'
});
assert.equal(response.status, expectedStatus);
const body = await response.json();
Adapt the example to the canonical contract. Substitute encoded concrete route parameter
values, construct query strings and JSON bodies, and verify actual status/body/headers.
For 204 or other empty responses use text() or skip JSON parsing. Use redirect:'manual'
when validating status/Location. Node fetch does not maintain browser cookies: obtain
required cookies from real responses using headers.getSetCookie(), strip attributes and
send them in a Cookie header for subsequent requests when this API requires it. Supply
only contract-required authentication; do not test another requirement's login flow as
an incidental dependency. Necessary existing sessions/accounts can be prepared via SQL.

Seed only required Given state directly through database with parameterized SQL and valid
values; use 0/1 booleans. Read the actual shared helper/SQL definitions rather than guessing
fixture arguments or password encodings. Initialization loads db/seeds/ENTITY.sql; reuse
existing prerequisites instead of assuming empty tables or duplicating identities. Arrange
scenario-specific absence/conflicting states in this isolated database. Do not invoke
another requirement's registration/creation API to manufacture Given data.

Within max_tests cover meaningful success and critical requirement-defined rejection.
Assert relevant persisted results/forbidden writes with SQL where needed; HTTP is the
only way to execute the operation. Do not assert unspecified wording, random identifiers,
hashes or timestamps. Do not inspect source text, add mocks, skip/focus tests or hardcode
success. Browser workflows belong to frontend E2E. Missing routes/behavior should fail real
assertions; do not expect 404/501 merely because this API is not implemented yet.

The compiler compiles the suite, runs accepted HTTP regressions, then runs this suite
against the actual backend. Assertion RED establishes missing behavior. Existing behavior
may already be GREEN; no stub replaces it. Backend startup failures are implementation
feedback, not proof the test is wrong. During generation repair test syntax/fixtures and
existing compilation problems, not the new operation. Generated tests remain correctable
against requirement evidence; preserve valid success/rejection coverage and previous tests.
"""

IMPLEMENT_INSTRUCTIONS = """Implement task.api according to its canonical contract against its generated tests.
Read the associated implementation files and extend or create business sources inside the supplied backend scope.
Choose meaningful filenames, reuse existing helpers, and extend shared API wiring incrementally. For an API module export:
export async function handle(request: ApiRequest, connection: Database.Database): Promise<ApiResponse>.
The export is always handle; signature.name identifies the business operation.
Tests exercise the operation through HTTP, not through an exported test alias. Import ApiRequest and ApiResponse from backend/src/api/types.ts
using a relative .js ESM import. Return status/body/optional headers, not Express objects.

Implement request validation, API preconditions, success/rejection responses and DB
effects according to the contract and scenarios. Use the supplied connection, parameterized
better-sqlite3 SQL, and transactions for related writes. Respect schema-generated integer
keys and use node:crypto for UUIDs or hashing when the schema/contract requires them.
Use the supplied test utilities and generated tests to understand existing fixture data
conventions. Preserve compatibility when reading those records. Production storage must
satisfy the contract and keep plaintext passwords out of persistent data.
Preserve required comparison rules and shared credential/header conventions.

Do not start a server, open another database, change schema or seed production data.
Use installed dependencies and Node standard modules. Implement the operation directly;
no DB-access primitive layer is generated. The compiler owns the HTTP test runner and fixture.
Predefined credentials in seeds/*.sql use seed_password_hash; its scrypt encoding is
defined in backend/src/db/seed.ts and must remain readable by credential handlers.
Read and edit task.api_wiring.registry to import this handle and register its actual
Express route, adapting params/query/body/headers and status/body/headers between HTTP
and the handler contract. Inspect app/server wiring when needed. The compiler will not
regenerate these files. Preserve all existing routes and middleware; insert/update this
API without replacing unrelated registrations or introducing duplicate routes. Extend
the existing registerApis implementation; never rebuild its body or route map with only
the current API. Earlier requirement implementations remain mandatory. Translate
contract path placeholders (including {name}) to syntax accepted by the installed router;
pass concrete parameter names and values to handle. Preserve cookies and error handling.
Use read_file with optional line ranges, to inspect related wiring; read only the relevant missing
lines and use a unique exact edit_file replacement. Do not start the production server in source code.
Preserve unrelated behavior when repairing other supplied writable backend sources.
Generated tests can be corrected against requirement and API evidence when their
expectations or fixtures are wrong or overly strict. Preserve required success and
rejection coverage; do not weaken a valid assertion to accept broken behavior.
SQL, designs, test utilities and compiler infrastructure remain references.
The compiler starts the real server and runs current/accepted HTTP API suites after TypeScript checks. Repair implementation
failures without weakening assertions or detecting tests to fake business behavior.
"""


def implement_backend_tdd(arc_dir: Path, pause: bool = False, max_turns: int = 10, max_tests: int = 5) -> dict:
    if max_turns < 1:
        raise ValueError("--max-turns must be positive")
    if max_tests < 1:
        raise ValueError("--max-tests must be positive")
    tree, schema, obligations = load_context(arc_dir)
    contracts = read_artifact(arc_dir, "backend_apis.json")
    output = arc_dir.parent.resolve()
    if not (output / "backend/src/db/initialize.ts").is_file():
        raise ValueError("Run main.py --stage 00 and main.py --stage 04 first")
    for name in schema["entities"]:
        if not (output / f"backend/src/db/tables/{name}.sql").is_file():
            raise ValueError(f"Missing implemented SQL for {name}; run step 04")
    prepare_runtime(output)
    console = DemoConsole(pause)
    console.show("TDD preparation | Install dependencies", f"Workspace: {output}\nCommand: npm install --include=dev --no-audit --no-fund")
    install_dependencies(output)
    checkpoint(output, stage="06", task="runtime", action="Prepare backend wiring and dependencies",
        details={"api_ids": list(contracts["apis"]), "http_test_runner": TEST_RUNNER_PATH})
    if not contracts["apis"]:
        report = {"status": "NO_APIS", "tests": {}, "red": {}, "green": {}, "agents": {}, "summary": {"tests": 0, "pass": 0, "fail": 0}}
        save_json(arc_dir / "backend_tdd.json", report)
        print("No Backend API Primitives require implementation; no tests or model calls were run.")
        return report
    checks = BackendChecks(output)
    model = TextModel() if contracts["apis"] else None
    owners = {}
    for aid in contracts["apis"]:
        ids = [rid for rid in tree.leaves if aid in contracts["requirements"].get(rid, [])]
        if ids:
            owners[aid] = ids
    targets = {aid: test_path(ids[0], aid) for aid, ids in owners.items()}
    report = {"status": "RUNNING", "requirements": {}, "tests": {}, "red": {}, "green": {}, "agents": {}}
    # Publish a current status before work; an old GREEN is never reused as proof.
    save_json(arc_dir / "backend_tdd.json", report)
    try:
        files_by_api = {aid: [relative] for aid, relative in targets.items()}
        accepted, attempted = [], set()
        for requirement_number, rid in enumerate(tree.leaves, 1):
            ids = contracts["requirements"].get(rid, [])
            pending = [aid for aid in ids if aid not in attempted]
            requirement_label = f"Requirement {requirement_number}/{len(tree.leaves)} {rid}"
            console.show(f"{requirement_label} | Begin requirement TDD", json.dumps(requirement_context(tree, rid), ensure_ascii=False, indent=2))
            report["requirements"][rid] = {"status": "RUNNING", "apis": ids}
            save_json(arc_dir / "backend_tdd.json", report)
            if not ids:
                report["requirements"][rid]["status"] = "NO_DIRECT_APIS"
                console.show(f"{requirement_label} | No direct APIs", "Child APIs are not inherited. Proceed to the next requirement.")
                save_json(arc_dir / "backend_tdd.json", report)
                continue
            reused = [aid for aid in ids if aid in accepted]
            if reused:
                console.show(f"{requirement_label} | Reuse accepted APIs", ", ".join(reused) + " already passed their canonical contract tests.")
            for aid in pending:
                attempted.add(aid)
                entry = report.setdefault("apis", {}).setdefault(aid, {"status": "GENERATING_TESTS", "api": aid, "requirements": owners[aid]})
                with implementation_task(output, entry, console, "08 / " + aid):
                    api_owners = owners[aid]
                    api = contracts["apis"][aid]
                    relative = targets[aid]
                    label = f"{rid} / {aid} (uses: {', '.join(api_owners)})"
                    console.show(f"{label} | Test Generation: P / Q / R / W", json.dumps(api, ensure_ascii=False, indent=2))

                    def test_gate(aid=aid):
                        chosen = relative
                        targets[aid] = chosen
                        files_by_api[aid] = [chosen]
                        generation_files = [targets[key] for key in [*accepted, aid]]
                        compiled = checks.typecheck(generation_files)
                        if compiled["returncode"]:
                            raise ValueError(f"Test TypeScript compilation failed: {compiled['output']}")
                        if accepted:
                            require_green(checks.tests([targets[key] for key in accepted]))
                        result = checks.tests(files_by_api[aid])
                        status = test_run_status(result)
                        if status == "RED_CONFIRMED":
                            report["red"][aid] = {key: result[key] for key in ("tests", "pass", "fail")}
                        entry["test_status"] = status
                        console.show(f"{aid} | HTTP tests: {status}", result["output"])
                        save_json(arc_dir / "backend_tdd.json", report)
                        checkpoint(output, stage="06", task=aid, action="Run HTTP tests before implementation",
                            status=status, details={"test_path": chosen, "checks": result})
                        return {"typecheck": compiled, "tests": result, "status": status}

                    context = {
                        "api_id": aid, "api": api,
                        "requirement": requirement_context(tree, rid),
                        "db_schema": related_schema(schema, [api]), "test_path": relative,
                        "max_tests": max_tests,
                        "support_module": TEST_SUPPORT_PATH,
                    }
                    workspace = FileTools(output, ["backend"], requirements=api_owners, stage="backend",
                        files=[relative, *supplied_sources(output, api, schema)], writable=[relative])
                    agent = run_file_agent(model, TEST_INSTRUCTIONS, context, workspace,
                        test_gate, max_turns, console, label + " / Test Generation")
                    for owner in api_owners:
                        report["tests"].setdefault(owner, {})[aid] = targets[aid]
                    report["agents"][f"tests:{aid}"] = {"turns": agent["turns"]}
                    save_json(arc_dir / "backend_tdd.json", report)
                    entry["status"] = "IMPLEMENTING"
                    api = contracts["apis"][aid]
                    console.show(f"{aid} | Implementation context", (
                        json.dumps(api, ensure_ascii=False, indent=2)
                        + "\nContract tests: " + ", ".join(files_by_api[aid])
                        + "\nAPI may directly operate the database; no further Primitive decomposition."
                    ))
                    regression_files = [relative for key in [*accepted, aid] for relative in files_by_api[key]]

                    def implementation_checks():
                        compiled = checks.typecheck(regression_files)
                        if compiled["returncode"]:
                            return {"typecheck": compiled, "tests": None}
                        tested = checks.tests(regression_files)
                        return {"typecheck": compiled, "tests": tested}

                    def implementation_gate():
                        result = implementation_checks()
                        if result["typecheck"]["returncode"]:
                            raise ValueError(result["typecheck"]["output"])
                        require_green(result["tests"])
                        return result

                    current = implementation_checks()
                    context = {
                        "api_id": aid, "api": api, "db_schema": related_schema(schema, [api]),
                        "requirement": requirement_context(tree, rid),
                        "api_wiring": {"registry": REGISTER_PATH, "app": "backend/src/app.ts",
                            "server": "backend/src/server.ts"},
                    }
                    workspace = FileTools(output, ["backend"], requirements=api_owners, stage="backend",
                        files=[REGISTER_PATH, *files_by_api[aid], *supplied_sources(output, api, schema)])
                    agent = run_file_agent(model, IMPLEMENT_INSTRUCTIONS, context, workspace,
                        implementation_gate, max_turns, console, aid + " / Implementation", feedback=current)
                    accepted.append(aid)
                    result = agent["checks"]["tests"]
                    report["green"][aid] = {key: result[key] for key in ("tests", "pass", "fail")}
                    report["agents"][f"implementation:{aid}"] = {"turns": agent["turns"]}
                    save_json(arc_dir / "backend_tdd.json", report)
                    console.show(f"{aid} | GREEN: contract and regression tests pass", result["output"])
                    entry["status"] = "GREEN"
                save_json(arc_dir / "backend_tdd.json", report)
            report["requirements"][rid]["status"] = "GREEN" if all(aid in accepted for aid in ids) else "FAILED"
            save_json(arc_dir / "backend_tdd.json", report)
            console.show(f"{requirement_label} | " + report["requirements"][rid]["status"], "Proceed to the next requirement; failed APIs remain recorded.")
        all_files = [targets[aid] for aid in accepted]
        console.show("Final regression | All requirements complete", "Compile the full backend and run all canonical API suites.")
        verification = final_checks(console,
            typecheck=(checks.typecheck, None),
            tests=(lambda: checks.tests(all_files), require_green if all_files else None),
            build=(checks.build, None))
        final = verification["tests"].get("result") or {}
        report["summary"] = {key: final.get(key, 0) for key in ("tests", "pass", "fail")}
        complete_report(report, report.get("apis", {}).values(), verification)
        save_json(arc_dir / "backend_tdd.json", report)
        print(f"TDD {report['status']}: {report['summary']}\nReport: {arc_dir / 'backend_tdd.json'}", flush=True)
        return report
    except BaseException as error:
        report["status"] = "FAILED"
        report["error"] = str(error)
        for requirement in report["requirements"].values():
            if requirement["status"] in {"RUNNING", "RED_CONFIRMED"}:
                requirement["status"] = "FAILED"
        save_json(arc_dir / "backend_tdd.json", report)
        raise
