"""Implement required startup data and repair database initialization failures."""

import json
import re
import uuid

from infrastructure.shared.agent.feedback import CheckFailure, compact_feedback
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.models.text import TextModel
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.shared.project.git import checkpoint
from infrastructure.stages.database.order import table_dependencies, implementation_groups
from infrastructure.stages.database.testing import DatabaseChecks
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.backend.context import requirement_context
from infrastructure.utils.files import read_artifact, save_json, save_text
from infrastructure.stages.database.runtime import seed_source
from infrastructure.stages.database.seeds import MANIFEST, SEED_RULES, seed_assertions
from infrastructure.stages.requirements.data import load_data, publish_seed_data, DATA_INSTRUCTIONS
from infrastructure.stages.backend.platform_files import IDENTITY_TABLES


SEED_PATH = "backend/src/db/seed.ts"

WIRING = (
    "backend/src/db/client.ts", "backend/src/db/initialize.ts", "backend/src/db/setup.ts",
    SEED_PATH,
    "backend/src/server.ts", "backend/src/app.ts", "backend/src/api/register.ts",
    "backend/scripts/copy-db.mjs", "package.json", "backend/package.json", "backend/tsconfig.json",
)

def implement_startup_data(arc_dir, schema, model, console, failures, max_turns=10):
    """Implement explicit source data against completed DDL in one coordinated pass."""
    output = arc_dir.parent.resolve()
    order = [name for group in implementation_groups(schema) for name in group]
    insert_paths = {name: f"backend/src/db/seeds/{name}.sql" for name in order}
    for name, relative in insert_paths.items():
        if not (output / relative).is_file():
            save_text(output / relative, f"-- Explicit startup data for {name}.\n")
    save_text(output / SEED_PATH, seed_source(order))
    catalog = load_data(arc_dir)
    publish_seed_data(output, schema, catalog)
    business = {key: row for key, row in catalog["records"].items()
        if row["lifecycle"] == "SEED" and row["entity"] != "test account"}
    if not business:
        return
    tree = RequirementTree(read_artifact(arc_dir, "requirements.json"))
    tree.validation_data = catalog
    from infrastructure.stages.backend.evidence import load_evidence
    tree.backend_evidence = load_evidence(arc_dir)
    tree.backend_foundation = read_artifact(arc_dir, "backend_foundation.json")
    protected = {insert_paths[name] for name in IDENTITY_TABLES if name in insert_paths} if tree.backend_foundation.get("enabled") else set()
    readable = set(insert_paths.values()) | {f"backend/src/db/tables/{name}.sql" for name in order} | {MANIFEST}
    files = FileTools(output, ["backend/src/db"], requirements=list(tree.leaves), stage="database",
        files=[], writable=(set(insert_paths.values()) - protected) | {MANIFEST}, readable=readable)
    task = {"catalog": business, "entities": schema["entities"],
        "source_sha256": catalog["source_sha256"], "schema_sha256": catalog["schema_sha256"],
        "manifest_path": MANIFEST, "insert_files": insert_paths,
        "requirements": [requirement_context(tree, rid) for rid in tree.leaves],
        "reserved_future_data": {key: row for key, row in catalog["records"].items()
            if row["lifecycle"] != "SEED"},
        "identity_references": {key: {"username": row["properties"].get("username"),
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "arc-backend:user:" + row["properties"]["username"]))}
            for key, row in catalog["records"].items() if row["entity"] == "test account"}}

    def generated():
        assertions = seed_assertions(output, schema, catalog)
        return {"status": "GENERATED", "source_records": len(business), "observed_rows": len(assertions)}

    with failures.task("startup data / semantic SQL implementation"):
        run_file_agent(model, DATA_INSTRUCTIONS + SEED_RULES, task, files, generated,
            max_turns, console, "Implement explicit startup data")


REPAIR_INSTRUCTIONS = '''Repair the actual database implementation and its startup wiring.
The compiler has already generated SQL and executed real checks; feedback contains
actual build, SQLite initialization or server startup failures. Use edit_file for repairs.

Use the canonical schema as authority. Repair the responsible SQL table files, related
foreign-key tables, initializer, client, setup/server entry point or SQL build-copy wiring.
Repair the responsible db/seeds/ENTITY.sql insertion files when prerequisite data fails.
seed.ts is only the shared SQL loader; do not move business row definitions into it.
Preserve the existing seed identities, credentials, values and relationships; correct
execution errors without redefining their business meaning. Semantic queries are disabled. The
loader runs after table creation in the initialization transaction, on every startup.
Keep it idempotent and preserve existing user data; do not remove it to make checks pass.
Keep CREATE TABLE IF NOT EXISTS and all canonical tables/fields. Opening the database
must create missing tables on every initialization/startup without deleting existing data.
Use the supplied better-sqlite3 client and real SQL files in both source and built output.
Preserve DATABASE_URL and PORT, createApp's existing health/API routes and signal cleanup.
Keep initialization transactional and foreign keys enabled. Startup must initialize the
same database connection used by the application before listening. Expected SQLite errors
must retain the failing SQL filename and underlying cause for diagnosis.

Do not replace the canonical schema with a test-only database, omit a failing table,
catch an error and pretend startup succeeded, disable constraints to hide a failure,
change the schema artifact, weaken checks, or add mocks. Do not drop existing user data.
Repair SQL to implement the supplied schema, including sqlite_type, composite primary
keys and entity.unique_constraints. An ER-imported schema is the same design contract:
its SQL implementation is repairable, but its fields, relationships and constraints
must not be redesigned to bypass an initialization failure.
This task owns database SQL and the supplied startup wiring; later API/UI tasks do not.
Use the supplied files first. Read missing related SQL/startup lines with read_file;
read the canonical table DDL for missing definitions. Use edit_file/replace for exact local repairs or
edit_file/create for a missing canonical SQL file under backend/src/db/tables or db/seeds.
The compiler rebuilds, initializes/reinitializes real databases, restores a missing table,
starts/restarts the compiled backend and initializes backend/data/app.db after every edit.
'''


def verify_database_runtime(arc_dir, schema, model, console, max_turns=10):
    output = arc_dir.parent.resolve()
    report = {"status": "CHECKING", "expected_tables": list(schema["entities"]), "repair_turns": 0}
    path = arc_dir / "db_checks.json"
    save_json(path, report)
    checks = DatabaseChecks(output, schema)
    manifest = None

    def gate():
        nonlocal manifest
        current = [(output / name).read_text(encoding="utf-8-sig") for name in ("package.json", "backend/package.json")]
        dependencies = ("tsx", "typescript", "better-sqlite3", "express")
        if (output / "backend/src/platform/settings.ts").is_file():
            dependencies += ("casbin", "xstate", "decimal.js")
        if (manifest is not None and current != manifest) or any(not (output / "node_modules" / name).exists() for name in dependencies):
            install_dependencies(output)
        manifest = current
        result = checks.run()
        report.update(status="GREEN" if result["returncode"] == 0 else "FAILED", checks=result)
        save_json(path, report)
        checkpoint(output, stage="04", task="database runtime", action="Execute real database and startup checks",
            status=report["status"], details=result)
        if result["returncode"]:
            raise CheckFailure("Database initialization or startup failed", result)
        return result

    try:
        gate()
        return report
    except (ValueError, RuntimeError) as error:
        feedback = getattr(error, "feedback", {"error": str(error)})

    sql_paths = {name: f"backend/src/db/tables/{name}.sql" for name in schema["entities"]}
    insert_paths = {name: f"backend/src/db/seeds/{name}.sql" for name in schema["entities"]}
    allowed = {*WIRING, *sql_paths.values(), *insert_paths.values()}
    protected = {"backend/src/app.ts", "backend/src/api/register.ts", "backend/src/db/initialize.ts", "backend/src/db/seed.ts",
        "backend/tsconfig.json", "backend/package.json", "package.json"} if (output / "backend/src/platform/settings.ts").is_file() else set()
    if protected:
        protected.update(insert_paths[name] for name in IDENTITY_TABLES if name in insert_paths)
    workspace = FileTools(output, ["backend", "package.json"], requirements=list(schema.get("requirements", {})),
        stage="database", files=WIRING, writable=allowed-protected, readable=allowed | {MANIFEST})
    task = {"table_order": [name for group in implementation_groups(schema) for name in group],
        "startup_data_loader": SEED_PATH, "seed_evidence": MANIFEST,
        "insertion_directory": "backend/src/db/seeds",
        "database_path": "backend/data/app.db", "entities": {}}
    dependencies = table_dependencies(schema)

    def repair_feedback(value):
        value = compact_feedback(value)
        text = json.dumps(value, ensure_ascii=False)
        selected = {name for name in sql_paths if f"{name}.sql" in text
            or re.search(r"Missing (?:table|column): " + re.escape(name) + r"(?!\w)", text)}
        if "SEED" in text or "seed" in text:
            selected.update(sql_paths)
        pending = list(selected)
        while pending:
            name = pending.pop()
            for target in dependencies[name]:
                if target not in selected:
                    selected.add(target)
                    pending.append(target)
        # Retain wiring and replace the previous failing table context instead of accumulating it.
        workspace.files = set(WIRING) | {MANIFEST} | {sql_paths[name] for name in selected} | {insert_paths[name] for name in selected}
        workspace.writable = (set(workspace.files) | set(insert_paths.values())) - protected - {MANIFEST}
        task["entities"] = {name: schema["entities"][name] for name in sorted(selected)}
        return value

    try:
        agent = run_file_agent(model or TextModel(), REPAIR_INSTRUCTIONS, task, workspace, gate,
            max_turns, console, "Database runtime repair", feedback=feedback,
            feedback_filter=repair_feedback)
        report.update(status="GREEN", repair_turns=agent["turns"])
        save_json(path, report)
        return report
    except (ValueError, RuntimeError) as error:
        report.update(status="FAILED", repair_turns=getattr(error, "turns", 0), error=str(error))
        save_json(path, report)
        raise
