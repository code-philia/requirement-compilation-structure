"""Step 08: TDD-driven enforcement of P, Q, and Dataflow Obligations."""

import json
from contextlib import ExitStack
from pathlib import Path

from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.stages.backend.context import load_context, requirement_context, api_requirement_uses, supplied_sources
from infrastructure.utils.files import read_artifact
from infrastructure.stages.backend.runtime import TEST_BINDINGS_PATH, prepare_runtime, sync_implementations, test_bindings_source, test_path
from infrastructure.stages.backend.testing import BackendChecks, require_green, require_red
from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import save_json, save_text


TEST_INSTRUCTIONS = """Write one canonical test suite for task.api, shared by all_requirement_uses, before
implementing the API. Base expected outcomes on the requirement scenarios, API I/O,
preconditions, postconditions and DB effects. Use db_schema and supplied SQL for fixtures.

Create a .test.ts file using task.new_file, or update test_path. Use node:test with
{test}, node:assert/strict as assert, and async test callbacks. Import the function
named api.signature.name from api_module; the compiler maps it to the API implementation.
Its signature is (request: ApiRequest, connection) => Promise<ApiResponse>.
Requests have params, query, body and headers; responses have status, body and optional
headers. They are plain transport objects, not Express request/response objects.
Compute relative .js imports to api_module and support_module from the chosen test path.

Use createTestDatabase(t) and request(partial) from support_module. Each test receives
a fresh real SQLite database. Seed Given state directly with parameterized SQL, supplying
required columns; do not invoke another API to manufacture fixtures. Bind booleans as 0/1.
Use the supplied test utility definitions for function signatures and fixture data
conventions. Construct fixtures compatible with those conventions and the API contract;
do not guess helper arguments or substitute arbitrary encoded values. No account is preseeded.

Within max_tests, prioritize meaningful success and requirement-defined rejection
branches. Combine related assertions rather than generating a separate case for each
condition or input variation. Assert response status, required fields/headers, persisted
results and forbidden writes. Verify DB outcomes with SQL, not source-code scans or
test-title labels. Treat R/W as possible effects; rejection need not perform them all.
Do not assert random IDs/hashes/timestamps or exact wording absent from the contract.
Cast response.body from unknown as needed. HTTP 501 is not a successful business result.

Use real API functions and SQLite, without mocks, skipped/focused tests or extra libraries.
Cross-API browser workflows belong to frontend E2E tests. The current test is writable;
other tests and infrastructure follow the files map. During test generation, repair
supplied writable sources only to restore existing behavior or compilation, not to
implement the new operation. The compiler compiles generated tests and runs accepted
API regressions, then establishes assertion RED against a 501 stub before implementation.
When repairing tests, preserve requirement-defined cases and assertions. Missing API
behavior is expected RED; fix test/fixture errors without deleting that behavioral coverage.
"""

IMPLEMENT_INSTRUCTIONS = """Implement task.api for all_requirement_uses against its generated tests.
Create the task.new_file target or update implementation_path. Export:
export async function handle(request: ApiRequest, connection: Database.Database): Promise<ApiResponse>.
The export is always handle; api.signature.name is the compiler-provided business alias
used by test bindings. Import ApiRequest and ApiResponse from backend/src/api/types.ts
using a relative .js ESM import. Return status/body/optional headers, not Express objects.

Implement request validation, API preconditions, success/rejection responses and DB
effects according to the contract and scenarios. Use the supplied connection, parameterized
better-sqlite3 SQL, and transactions for related writes. Respect schema-generated integer
keys and use node:crypto for UUIDs or hashing when the schema/contract requires them.
Use the supplied test utilities and frozen tests to understand existing fixture data
conventions. Preserve compatibility when reading those records. Production storage must
satisfy the contract and keep plaintext passwords out of persistent data.
Preserve required comparison rules and shared credential/header conventions.

Do not start a server, open another database, change schema or seed production data.
Use installed dependencies and Node standard modules. Implement the operation directly;
no DB-access primitive layer is generated. Routing and test aliases are compiler-owned.
Preserve unrelated behavior when repairing other supplied writable backend sources.
Tests, SQL, designs and compiler infrastructure are references according to files.
The compiler runs TypeScript and current/accepted API tests. Repair implementation
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
        raise ValueError("Run 00_project_initialization.py and 05_implement_db.py first")
    for name in schema["entities"]:
        if not (output / f"backend/src/db/tables/{name}.sql").is_file():
            raise ValueError(f"Missing implemented SQL for {name}; run step 05")
    prepare_runtime(output, contracts["apis"])
    console = DemoConsole(pause)
    console.show("TDD preparation | Install dependencies", f"Workspace: {output}\nCommand: npm install --include=dev --no-audit --no-fund")
    install_dependencies(output)
    if not contracts["apis"]:
        report = {"status": "NO_APIS", "tests": {}, "red": {}, "green": {}, "agents": {}, "summary": {"tests": 0, "pass": 0, "fail": 0}}
        save_json(arc_dir / "backend_tdd.json", report)
        print("No Backend API Primitives require implementation; no tests or model calls were run.")
        return report
    checks = BackendChecks(output)
    selection = SourceFiles(output, root="backend/src", tests_root="backend/tests")
    model = TextModel() if contracts["apis"] else None
    owners = {aid: [rid for rid in tree.postorder if aid in contracts["requirements"][rid]] for aid in contracts["apis"]}
    targets = {aid: selected_path(output, "backend_test", aid) or test_path(ids[0], aid) for aid, ids in owners.items()}
    report = {"status": "RUNNING", "requirements": {}, "tests": {}, "red": {}, "green": {}, "agents": {}}
    # Publish a current status before work; an old GREEN is never reused as proof.
    save_json(arc_dir / "backend_tdd.json", report)
    try:
        files_by_api = {aid: [relative] for aid, relative in targets.items()}
        accepted = []
        for requirement_number, rid in enumerate(tree.postorder, 1):
            ids = contracts["requirements"][rid]
            pending = [aid for aid in ids if aid not in accepted]
            requirement_label = f"Requirement {requirement_number}/{len(tree.requirements)} {rid}"
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
            generated = []
            for aid in pending:
                api_owners = owners[aid]
                api = contracts["apis"][aid]
                relative = targets[aid]
                label = f"{rid} / {aid} (uses: {', '.join(api_owners)})"
                console.show(f"{label} | Test Generation: P / Q / R / W", json.dumps(api, ensure_ascii=False, indent=2))

                def test_gate(aid=aid):
                    chosen = selected_path(output, "backend_test", aid) or relative
                    targets[aid] = chosen
                    files_by_api[aid] = [chosen]
                    generation_files = [targets[key] for key in [*accepted, *generated, aid]]
                    compiled = checks.typecheck(generation_files)
                    if compiled["returncode"]:
                        raise ValueError(f"Test TypeScript compilation failed: {compiled['output']}")
                    if accepted:
                        require_green(checks.tests([targets[key] for key in accepted]))
                    return compiled

                context = {
                    "api_id": aid, "api": api,
                    "all_requirement_uses": api_requirement_uses(tree, contracts["requirements"], aid),
                    "db_schema": schema["entities"], "test_path": relative if (output / relative).is_file() else None,
                    "max_tests": max_tests,
                    "api_module": TEST_BINDINGS_PATH, "support_module": "backend/tests/support/context.ts",
                }
                workspace = selection.workspace(target=("backend_test", aid), existing=relative,
                    references=[TEST_BINDINGS_PATH, *supplied_sources(output, api, schema)])
                agent = run_file_agent(model, TEST_INSTRUCTIONS, context, workspace,
                    test_gate, max_turns, console, label + " / Test Generation",
                    feedback_filter=lambda value: selection.feedback(workspace, value))
                for owner in api_owners:
                    report["tests"].setdefault(owner, {})[aid] = targets[aid]
                report["agents"][f"tests:{aid}"] = {"turns": agent["turns"]}
                save_json(arc_dir / "backend_tdd.json", report)
                generated.append(aid)
            # --- Extension point 08A: test-only RED bindings -------------------
            # Exercise the same frozen assertions with 501 test bindings; never
            # overwrite actual business implementations to establish RED.
            binding_source = (output / TEST_BINDINGS_PATH).read_text(encoding="utf-8-sig")
            try:
                save_text(output / TEST_BINDINGS_PATH,
                    test_bindings_source(output, contracts["apis"], stubbed=pending))
                for aid in pending:
                    result = checks.tests(files_by_api[aid])
                    require_red(result)
                    report["red"][aid] = {key: result[key] for key in ("tests", "pass", "fail")}
                    console.show(f"{aid} | RED: contract assertions fail against the test stub", result["output"])
            finally:
                save_text(output / TEST_BINDINGS_PATH, binding_source)
            if pending:
                report["requirements"][rid]["status"] = "RED_CONFIRMED"
            save_json(arc_dir / "backend_tdd.json", report)
            for aid in pending:
                api = contracts["apis"][aid]
                console.show(f"{aid} | Implementation context", (
                    json.dumps(api, ensure_ascii=False, indent=2)
                    + "\nFrozen tests: " + ", ".join(files_by_api[aid])
                    + "\nAPI may directly operate the database; no further Primitive decomposition."
                ))
                regression_files = [relative for key in [*accepted, aid] for relative in files_by_api[key]]

                def implementation_checks():
                    sync_implementations(output, contracts["apis"])
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

                entry = selected_path(output, "api", aid)
                current = implementation_checks() if entry and (output / entry).is_file() else None
                if current and current["tests"] and not current["tests"]["returncode"] and current["tests"]["tests"]:
                    agent = {"turns": 0, "checks": current}
                else:
                    context = {
                        "api_id": aid, "api": api, "db_schema": schema["entities"],
                        "all_requirement_uses": api_requirement_uses(tree, contracts["requirements"], aid),
                        "implementation_path": selected_path(output, "api", aid),
                    }
                    workspace = selection.workspace(target=("api", aid),
                        references=[*files_by_api[aid], *supplied_sources(output, api, schema)])
                    agent = run_file_agent(model, IMPLEMENT_INSTRUCTIONS, context, workspace,
                        implementation_gate, max_turns, console, aid + " / Implementation", feedback=current,
                        feedback_filter=lambda value: selection.feedback(workspace, value))
                accepted.append(aid)
                result = agent["checks"]["tests"]
                report["green"][aid] = {key: result[key] for key in ("tests", "pass", "fail")}
                report["agents"][f"implementation:{aid}"] = {"turns": agent["turns"]}
                save_json(arc_dir / "backend_tdd.json", report)
                console.show(f"{aid} | GREEN: contract and regression tests pass", result["output"])
            report["requirements"][rid]["status"] = "GREEN"
            save_json(arc_dir / "backend_tdd.json", report)
            console.show(f"{requirement_label} | Requirement GREEN", "All direct APIs passed. Proceed to the next requirement.")
        all_files = [targets[aid] for aid in accepted]
        console.show("Final regression | All requirements complete", "Compile the full backend and run all canonical API suites.")
        compiled = checks.typecheck()
        if compiled["returncode"]:
            raise ValueError(compiled["output"])
        final = checks.tests(all_files)
        if all_files:
            require_green(final)
        report["status"] = "GREEN"
        report["summary"] = {key: final[key] for key in ("tests", "pass", "fail")}
        save_json(arc_dir / "backend_tdd.json", report)
        print(f"TDD GREEN: {report['summary']}\nReport: {arc_dir / 'backend_tdd.json'}", flush=True)
        return report
    except BaseException as error:
        report["status"] = "FAILED"
        report["error"] = str(error)
        for requirement in report["requirements"].values():
            if requirement["status"] in {"RUNNING", "RED_CONFIRMED"}:
                requirement["status"] = "FAILED"
        save_json(arc_dir / "backend_tdd.json", report)
        raise


def main() -> None:
    parser = create_parser("Step 08: TDD-driven API Implementation (P / Q / Dataflow Obligations)")
    parser.add_argument("--max-turns", type=int, default=10, help="Maximum edit rounds per test/implementation agent")
    parser.add_argument("--max-tests", type=int, default=5, help="Maximum key contract tests per API (default: 5)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output = resolve_directories(args)
            stack.enter_context(console_log(output, debug_model_io=args.debug_model_io))
            implement_backend_tdd(output / ".arc", args.pause, args.max_turns, args.max_tests)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
