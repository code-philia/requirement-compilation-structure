"""Implement required startup data and repair database initialization failures."""

import json
import re

from infrastructure.shared.agent.discovery import ContextIndex, project_index
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
from infrastructure.utils.files import read_artifact, save_json


SEED_PATH = "backend/src/db/seed.ts"

WIRING = (
    "backend/src/db/client.ts", "backend/src/db/initialize.ts", "backend/src/db/setup.ts",
    SEED_PATH,
    "backend/src/server.ts", "backend/src/app.ts", "backend/src/api/register.ts",
    "backend/scripts/copy-db.mjs", "package.json", "backend/package.json", "backend/tsconfig.json",
)

SEED_INSTRUCTIONS = '''Maintain task.seed_path for the current requirement's required startup data.
The template exports seedDatabase(connection: Database.Database): void. Use read_file
and edit_file to extend this shared script while preserving earlier requirements.
Add to the existing seedDatabase implementation; never replace its body or seed collection
with only the current requirement's records. Previously required startup data must remain.
The initializer calls it synchronously after creating all tables and before listening,
inside the same transaction with foreign keys enabled.

Add only data the original requirement explicitly says the installed system must contain:
for example required catalogue entries, built-in roles, settings or a predefined account.
A scenario's Given records, example names and reference-image objects are not automatically
startup data. Do not manufacture demonstration records or seed every test scenario.
If this requirement adds no startup data, leave the script unchanged and return tool_calls=[].
Keep short requirement-ID comments near the corresponding initialization code.

Use the canonical schema and real parameterized better-sqlite3 statements. Query related
schema or SQL when needed; task.entities is only the current requirement's projection.
Seed referenced rows before dependent rows. Use stable identifiers where the schema permits;
look up actual foreign keys rather than assuming auto-generated IDs. Respect documented
credential encodings; do not import test utilities into production code or persist plaintext
passwords. Use installed dependencies and Node standard modules only.

This function runs on every startup and db:init, including on an existing database.
Insert missing required records using their stable business identity; do not duplicate them,
replace existing rows, reset passwords or overwrite user edits on restart. Prefer an explicit
existence check or a targeted ON CONFLICT clause over INSERT OR IGNORE, which can hide invalid
data. Do not swallow errors, disable constraints, drop data, change table definitions, open
another connection, start a server or run asynchronous work. No additional seed registry,
migration framework or model-generated metadata is needed. Real build and initialization
checks run after startup-data generation; failures are repaired by the database owner.
'''


def implement_startup_data(arc_dir, schema, model, console, failures, max_turns=10):
    """Maintain one executable script, focusing on one original requirement at a time."""
    output = arc_dir.parent.resolve()
    tree = RequirementTree(read_artifact(arc_dir, "requirements.json"))
    for rid in tree.requirements:
        requirement = requirement_context(tree, rid)
        if not requirement["description"] and not requirement["steps"]:
            continue
        with failures.task("startup data / " + rid):
            names = set()
            for symbol in schema["requirements"].get(rid, []):
                names.add(symbol.split(".", 1)[0])
            entities = {name: schema["entities"][name] for name in sorted(names)}
            references = [f"backend/src/db/tables/{name}.sql" for name in entities
                if (output / f"backend/src/db/tables/{name}.sql").is_file()]
            references.append("backend/tests/support/context.ts")
            files = FileTools(output, [SEED_PATH], references)
            # Read relevant script spans on demand instead of pinning all earlier seed code.
            files.files.discard(SEED_PATH)
            task = {"requirement": requirement, "entities": entities, "seed_path": SEED_PATH}

            def generated():
                if not (output / SEED_PATH).is_file():
                    raise ValueError("Maintain the required startup data script at " + SEED_PATH)
                return {"status": "GENERATED", "path": SEED_PATH}

            run_file_agent(model, SEED_INSTRUCTIONS, task, files, generated,
                max_turns, console, "Startup data / " + rid, context_index=project_index(output))


REPAIR_INSTRUCTIONS = '''Repair the actual database implementation and its startup wiring.
The compiler has already generated SQL and executed real checks; feedback contains
actual build, SQLite initialization or server startup failures. Use edit_file for repairs.

Use the canonical schema as authority. Repair the responsible SQL table files, related
foreign-key tables, initializer, client, setup/server entry point or SQL build-copy wiring.
Repair db/seed.ts when required startup data fails. Preserve requirement-defined seed data;
read the original requirement using semantic discovery before changing its meaning. This
script runs after table creation in the initialization transaction, on every startup.
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
This task owns database SQL and the supplied startup wiring; later API/UI tasks do not.
Use the supplied files first. Read missing related SQL/startup lines with read_file;
query kind=schema for definitions. Use edit_file/replace for exact local repairs or
edit_file/create for a missing canonical SQL file under backend/src/db/tables.
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
        if (manifest is not None and current != manifest) or any(not (output / "node_modules" / name).exists() for name in dependencies):
            install_dependencies(output)
        manifest = current
        result = checks.run()
        report.update(status="GREEN" if result["returncode"] == 0 else "FAILED", checks=result)
        save_json(path, report)
        checkpoint(output, stage="05", task="database runtime", action="Execute real database and startup checks",
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
    allowed = {*WIRING, *sql_paths.values()}
    workspace = FileTools(output, WIRING, allow_write=lambda path: path in allowed)
    task = {"table_order": [name for group in implementation_groups(schema) for name in group],
        "startup_data_script": SEED_PATH,
        "database_path": "backend/data/app.db", "entities": {}}
    dependencies = table_dependencies(schema)

    def repair_feedback(value):
        value = compact_feedback(value)
        text = json.dumps(value, ensure_ascii=False)
        selected = {name for name in sql_paths if f"{name}.sql" in text
            or re.search(r"Missing (?:table|column): " + re.escape(name) + r"(?!\w)", text)}
        pending = list(selected)
        while pending:
            name = pending.pop()
            for target in dependencies[name]:
                if target not in selected:
                    selected.add(target)
                    pending.append(target)
        # Retain wiring and replace the previous failing table context instead of accumulating it.
        workspace.files = set(WIRING) | {sql_paths[name] for name in selected}
        workspace.writable = set(workspace.files)
        task["entities"] = {name: schema["entities"][name] for name in sorted(selected)}
        return value

    index = project_index(output)
    def collections():
        records = index.records()
        records["file"].update({name: {} for name in allowed if (output / name).is_file()})
        return records

    try:
        agent = run_file_agent(model or TextModel(), REPAIR_INSTRUCTIONS, task, workspace, gate,
            max_turns, console, "Database runtime repair", feedback=feedback,
            feedback_filter=repair_feedback, context_index=ContextIndex(collections, output))
        report.update(status="GREEN", repair_turns=agent["turns"])
        save_json(path, report)
        return report
    except (ValueError, RuntimeError) as error:
        report.update(status="FAILED", repair_turns=getattr(error, "turns", 0), error=str(error))
        save_json(path, report)
        raise
