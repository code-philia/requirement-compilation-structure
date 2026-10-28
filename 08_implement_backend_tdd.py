"""Step 08: TDD-driven enforcement of P, Q, and Dataflow Obligations."""

import json
from contextlib import ExitStack
from pathlib import Path

from infrastructure.shared.agent.files import FileTools, project_structure
from infrastructure.shared.agent.traceability import FileIndex
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.stages.backend.context import load_context, requirement_context, supplied_sources
from infrastructure.utils.files import read_artifact
from infrastructure.stages.backend.contracts import validate_contracts
from infrastructure.stages.backend.primitives import validate_design
from infrastructure.stages.backend.runtime import PROTECTED, TEST_BINDINGS_PATH, prepare_runtime, sync_implementations, test_bindings_source, test_path
from infrastructure.stages.backend.testing import BackendChecks, assert_frozen, require_green, require_red, snapshot_tests, test_budget, validate_test_source
from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.shared.models.text import TextModel
from infrastructure.stages.database.obligations.records import field_symbols
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import save_json, save_text


TEST_INSTRUCTIONS = """Generate contract tests BEFORE implementing the API.
Generate ONE canonical suite for the API, shared by all its requirement uses.
Keep at most the supplied test_budget cases. Prefer one meaningful success case,
one representative invalid-input case, and the key business rejection cases. Combine
related contract assertions in a case. Do not generate one test per missing/empty field
or expand table-driven input variations. Rewrite an oversized current file rather
than copying it. Cover response branches and critical P/Q/R/W using these few cases.
Write only the supplied test_path. Use node:test with a named import { test } and
node:assert/strict (default import assert), with literal test("title", async (t)=>...) cases.
The API named function is async (request: ApiRequest, connection) => ApiResponse.
ApiRequest contains params/query/body/headers; ApiResponse contains status/body/optional
headers. It does NOT return an Express Response. Use the supplied exact import paths.
Use createTestDatabase(t), request(partial), and fixturePasswordHash(password) from the
read-only support context. Every test gets a fresh real SQLite database and real tables.
Prepare Given fixtures with SQL inserts (provide all NOT NULL columns); do not call a
different API to fabricate Given state. Credential fixture format is scrypt$saltHex$hashHex
where hash=scryptSync(password, Buffer.from(saltHex,'hex'),64). No account is preseeded.
Bind SQLite booleans as integers 0/1, not JavaScript boolean values.
Derive assertions from canonical precondition/request and postcondition/response, DB
effects, and supplied scenarios. Cover every P and Q; include required invalid inputs,
failure-without-writes, meaningful successes and persistence. Never test 501 as success.
Test titles include every covered P-/Q- ID and R:Entity.field / W:Entity.field labels.
One success test can cover many field labels. Every declared P/Q/R/W label must occur
in an actual test title. Do not merely place coverage IDs in comments. Assert status,
returned fields/headers and actual DB state, not the implementation source code.
When a response header is consumed by another API, assert the complete transport
identity and perform a producer-to-consumer round trip; checking only that a header
exists is insufficient. Keep shared cookie/token names in the canonical contract.
Use casts for response.body when needed (its transport type is unknown). Do not assume
generated UUIDs, timestamps, random hashes, exact error wording, or fields not in the
contract. Tests may not be skipped, focused, mocked, or weaken the contract. No external
libraries beyond the installed stack and Node standard library. Do not edit app code,
SQL, test support, or other test files. The gate checks test traceability and TypeScript;
the explicit RED phase happens once the current requirement's tests are generated. All needed file paths and
contents are supplied. Submit edit_files with an edits list for this test file.
Use create only for a nonexistent file; otherwise replace exact old_content.
A passing gate accepts the proposal.
"""

IMPLEMENT_INSTRUCTIONS = """Implement the selected Backend API Primitive against its
canonical contract and the frozen tests. Preserve its signature: an async exported named
function (request: ApiRequest, connection: Database.Database): Promise<ApiResponse>.
Implement request validation, precondition failures, postconditions, database reads and
writes, using parameterized better-sqlite3 SQL and transactions for related writes.
An API directly accesses the database; DB Access Primitive decomposition is an extension.
Return status/body/optional headers, not Express Response objects. Never create a server,
open another database, alter schema, seed production data, or modify test files.
You choose implementation filenames and paths within backend/src. The shallow project
structure and requirement/module file associations are supplied. The compiler supplies
relevant files' complete current contents in file_context.files each turn; edit only
those existing files. You may create modules and shared helpers at new source paths.
Import ApiRequest and ApiResponse from the supplied backend/src/api/types.ts using the
correct relative .js ESM import for your chosen location. Compiler-owned routing and test bindings are protected. Routes import your selected
implementation directly; no per-API proxy source file is generated. In edit_files, include
entrypoint: {"path": "your/chosen/source.ts", "export": "yourNamedFunction"} to bind the
current API to your module. Preserve its required function arguments and return type.
app.ts and register.ts are wired deterministically by Python, never by this agent.
Use node:crypto for UUIDs and credential handling; no new dependencies. For credential
APIs verify existing scrypt$saltHex$hashHex fixtures with scryptSync(...,64). Store salted
hashes, never plaintext. Keep exact username comparison and shared cookie conventions
from contracts. Errors must not leave partial account/session writes. Do not change
contracts, R/W declarations, assertions, SQL tables, routing infrastructure or test gates.
Tool checks run TypeScript plus the current and already accepted APIs' frozen suites.
Use the supplied file contents and project tree to organize your implementation.
There is no file-reading tool. Propose edit_files with workspace-relative paths,
operations, exact old_content, and new_content. Inspect feedback and repair until GREEN. Finish is accepted only
after external checks pass. Do not import
test modules or detect tests to fake behavior. API core behavior must also work through
the deterministic Express adapter used by the application's server.
"""


def implement_backend_tdd(arc_dir: Path, pause: bool = False, max_turns: int = 18, max_tests: int = 5) -> dict:
    if max_turns < 1:
        raise ValueError("--max-turns must be positive")
    if max_tests < 1:
        raise ValueError("--max-tests must be positive")
    tree, schema, obligations = load_context(arc_dir)
    design = read_artifact(arc_dir, "backend_apis.json")
    contracts = read_artifact(arc_dir, "backend_contracts.json")
    validate_design(design, obligations, field_symbols(schema), tree=tree)
    validate_contracts(contracts, design)
    output = arc_dir.parent.resolve()
    if not (output / "backend/src/db/initialize.ts").is_file():
        raise ValueError("Run 00_project_initialization.py and 05_implement_db.py first")
    for name in schema["entities"]:
        if not (output / f"backend/src/db/tables/{name}.sql").is_file():
            raise ValueError(f"Missing implemented SQL for {name}; run step 05")
    index = FileIndex(output)
    prepare_runtime(output, contracts["apis"], index, contracts["requirements"])
    console = DemoConsole(pause)
    console.show("Backend core project structure", project_structure(output))
    console.show("TDD preparation | Install dependencies", f"Workspace: {output}\nCommand: npm install --include=dev --no-audit --no-fund")
    install_dependencies(output)
    if not contracts["apis"]:
        report = {"status": "NO_APIS", "tests": {}, "red": {}, "green": {}, "agents": {}, "summary": {"tests": 0, "pass": 0, "fail": 0}}
        save_json(arc_dir / "backend_tdd.json", report)
        print("No Backend API Primitives require implementation; no tests or model calls were run.")
        return report
    checks = BackendChecks(output)
    model = TextModel() if contracts["apis"] else None
    owners = {aid: [rid for rid in tree.postorder if aid in contracts["requirements"][rid]] for aid in contracts["apis"]}
    targets = {aid: test_path(ids[0], aid) for aid, ids in owners.items()}
    budgets = {aid: test_budget(api, max_tests) for aid, api in contracts["apis"].items()}
    # Retire only earlier compiler-owned duplicate suites. Unlisted user tests
    # are preserved; failed migrations retain their retirement list for retry.
    previous = json.loads((arc_dir / "backend_tdd.json").read_text(encoding="utf-8-sig")) if (arc_dir / "backend_tdd.json").is_file() else {}
    owned = {path for ids in previous.get("tests", {}).values() for path in ids.values()}
    retired = sorted((owned | set(previous.get("retired_tests", []))) - set(targets.values()))
    for relative in retired:
        if not isinstance(relative, str) or not relative.startswith("backend/tests/") or not relative.endswith(".test.ts") or not (output / relative).resolve().is_relative_to(output / "backend/tests"):
            raise ValueError("Invalid compiler-owned test path in previous TDD report")
    report = {"status": "RUNNING", "requirements": {}, "tests": {}, "red": {}, "green": {}, "agents": {}}
    if retired:
        report["retired_tests"] = retired
    # Publish a current status before work; an old GREEN is never reused as proof.
    save_json(arc_dir / "backend_tdd.json", report)
    try:
        files_by_api = {aid: [relative] for aid, relative in targets.items()}
        accepted = []
        frozen = snapshot_tests(output, [])
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

                generation_files = [targets[key] for key in [*accepted, *generated, aid]]

                def generation_checks():
                    assert_frozen(output, frozen)
                    return checks.typecheck(generation_files)

                def test_gate(relative=relative, api=api):
                    validate_test_source((output / relative).read_text(encoding="utf-8-sig"), api, budgets[aid])
                    assert_frozen(output, frozen)
                    compiled = checks.typecheck(generation_files)
                    if compiled["returncode"]:
                        raise ValueError(f"Test TypeScript compilation failed: {compiled['output']}")
                    return compiled

                context = {
                    "requirement": requirement_context(tree, rid), "api_id": aid, "api": api,
                    "all_requirement_uses": [requirement_context(tree, owner) for owner, bindings in contracts["requirements"].items() if aid in bindings],
                    "db_schema": schema, "test_path": relative,
                    "test_budget": budgets[aid],
                    "api_import": "../support/apis.js", "support_import": "../support/context.js",
                    "source_files": supplied_sources(output, api, schema),
                }
                agent = run_file_agent(model, TEST_INSTRUCTIONS, context,
                    FileTools(output, {relative}, generation_checks, index=index, requirements=api_owners, module=f"tests:{aid}"), test_gate, max_turns, console, label + " / Test Generation")
                index.record([relative], api_owners, f"tests:{aid}")
                for owner in api_owners:
                    report["tests"].setdefault(owner, {})[aid] = relative
                report["agents"][f"tests:{aid}"] = {"turns": agent["turns"]}
                save_json(arc_dir / "backend_tdd.json", report)
                generated.append(aid)
                frozen.update(snapshot_tests(output, [relative]))
            # --- Extension point 08A: test-only RED bindings -------------------
            # Exercise the same frozen assertions with 501 test bindings; never
            # overwrite actual business implementations to establish RED.
            binding_source = (output / TEST_BINDINGS_PATH).read_text(encoding="utf-8-sig")
            try:
                save_text(output / TEST_BINDINGS_PATH,
                    test_bindings_source(output, contracts["apis"], index, stubbed=pending))
                for aid in pending:
                    result = checks.tests(files_by_api[aid])
                    if result.get("tests", 0) > budgets[aid]:
                        raise ValueError(f"Keep at most {budgets[aid]} executed tests for {aid}")
                    assert_frozen(output, frozen)
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
                console.show(f"{aid} | Backend structure and related files", project_structure(output) + "\n\nRelated files:\n" + "\n".join(index.files_for(owners[aid], f"backend:{aid}")))
                console.show(f"{aid} | Implementation context", (
                    json.dumps(api, ensure_ascii=False, indent=2)
                    + "\nFrozen tests: " + ", ".join(files_by_api[aid])
                    + "\nAPI may directly operate the database; no further Primitive decomposition."
                ))
                regression_files = [relative for key in [*accepted, aid] for relative in files_by_api[key]]

                def implementation_checks():
                    sync_implementations(output, contracts["apis"], index, contracts["requirements"])
                    assert_frozen(output, frozen)
                    compiled = checks.typecheck(regression_files)
                    if compiled["returncode"]:
                        return {"typecheck": compiled, "tests": None}
                    tested = checks.tests(regression_files)
                    assert_frozen(output, frozen)
                    return {"typecheck": compiled, "tests": tested}

                def implementation_gate():
                    result = implementation_checks()
                    if result["typecheck"]["returncode"]:
                        raise ValueError(result["typecheck"]["output"])
                    require_green(result["tests"])
                    return result

                current = implementation_checks()
                if current["tests"] and not current["tests"]["returncode"] and current["tests"]["tests"]:
                    agent = {"turns": 0, "checks": implementation_gate()}
                else:
                    context = {
                        "requirement": requirement_context(tree, rid),
                        "api_id": aid, "api": api, "db_schema": schema,
                        "requirement_uses": [requirement_context(tree, rid) for rid, bindings in contracts["requirements"].items() if aid in bindings],
                        "module_id": f"backend:{aid}",
                        "project_structure": project_structure(output),
                        "related_files": index.files_for(owners[aid], f"backend:{aid}"),
                        "existing_contracts": contracts["apis"], "frozen_tests": {path: (output / path).read_text(encoding="utf-8-sig") for path in files_by_api[aid]},
                        "source_files": supplied_sources(output, api, schema),
                        "initial_feedback": current,
                    }
                    agent = run_file_agent(model, IMPLEMENT_INSTRUCTIONS, context,
                        FileTools(output, None, implementation_checks,
                            roots=("backend/src",), read_roots=("backend",),
                            context_files=("backend/package.json",),
                            protected=PROTECTED,
                            index=index, requirements=owners[aid], module=f"backend:{aid}"),
                        implementation_gate, max_turns, console, aid + " / Implementation")
                index.record(index.files_for(module=f"backend:{aid}"), owners[aid], f"backend:{aid}")
                accepted.append(aid)
                result = agent["checks"]["tests"]
                report["green"][aid] = {key: result[key] for key in ("tests", "pass", "fail")}
                report["agents"][f"implementation:{aid}"] = {"turns": agent["turns"]}
                save_json(arc_dir / "backend_tdd.json", report)
                console.show(f"{aid} | GREEN: contract and regression tests pass", result["output"])
            report["requirements"][rid]["status"] = "GREEN"
            save_json(arc_dir / "backend_tdd.json", report)
            console.show(f"{requirement_label} | Requirement GREEN", "All direct APIs passed. Proceed to the next requirement.")
        # Retire obsolete compiler-owned suites only after every requirement is GREEN.
        for relative in retired:
            (output / relative).unlink(missing_ok=True)
        report.pop("retired_tests", None)
        save_json(arc_dir / "backend_tdd.json", report)
        all_files = [targets[aid] for aid in accepted]
        console.show("Final regression | All requirements complete", "Compile the full backend and run all canonical API suites.")
        compiled = checks.typecheck()
        if compiled["returncode"]:
            raise ValueError(compiled["output"])
        final = checks.tests(all_files)
        assert_frozen(output, frozen)
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
    parser.add_argument("--max-turns", type=int, default=18, help="Maximum tool turns per test/implementation agent")
    parser.add_argument("--max-tests", type=int, default=5, help="Maximum key contract tests per API (default: 5)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output = resolve_directories(args)
            stack.enter_context(console_log(output))
            implement_backend_tdd(output / ".arc", args.pause, args.max_turns, args.max_tests)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
