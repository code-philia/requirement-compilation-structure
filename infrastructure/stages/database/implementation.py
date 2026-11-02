"""Implement required startup data and repair database initialization failures."""

import json
import re

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


SEED_PATH = "backend/src/db/seed.ts"

WIRING = (
    "backend/src/db/client.ts", "backend/src/db/initialize.ts", "backend/src/db/setup.ts",
    SEED_PATH,
    "backend/src/server.ts", "backend/src/app.ts", "backend/src/api/register.ts",
    "backend/scripts/copy-db.mjs", "package.json", "backend/package.json", "backend/tsconfig.json",
)

SEED_INSTRUCTIONS = '''Read the current requirement and incrementally maintain its prerequisite database rows.
Each table has one insertion file: backend/src/db/seeds/ENTITY.sql. The compiler has
created these files and a dependency-ordered seed.ts loader. Edit only the insertion
SQL files; do not put records or INSERT statements in seed.ts or the table DDL files.
task.insert_files identifies the current tables. task.table_names lists the canonical
table names; their DDL is in backend/src/db/tables/ENTITY.sql. If another table is needed,
read its DDL and insertion SQL directly. Semantic queries are not available in this stage.
Only canonical database table/insertion files are readable; other application files and
requirements are outside this task. The password helper contract is specified below;
there is no need to inspect the seed loader or other infrastructure.

Identify data that must EXIST BEFORE this requirement's When actions:
- System/domain data users cannot create through the application, such as train services,
  reference catalogues, built-in roles or already stocked books.
- Existing users, books, shelves and other domain records stated in Given or explicit
  seed/prerequisite sections. Include these even when another requirement implements
  their creation: login must be testable with a pre-existing account independently of
  registration, and reading/editing content must not depend on its creation workflow.
- Include the related parent rows and association rows needed to make these records valid.
Preserve exact names, credentials, contents, relationships and initial status supplied by
requirements. For omitted mandatory fields, choose minimal valid deterministic values.
Do not discard prerequisites merely because they occur in a scenario rather than a
sentence saying "system startup". Use the supplied complete requirement and its scenarios.
If a generic reference such as "an existing verified account" does not identify concrete
records, do not invent a separate account, password or object. The defining leaf requirement
will supply those records during this pass. Fill omitted mandatory fields only for records
whose identity is actually established by this requirement.

Do not pre-execute the current When/Then. A record created by this scenario's operation
must remain absent until that operation. Do not fabricate authenticated sessions, personal
history, favorites or drafts that the requirement explicitly establishes through login
or other UI actions. Browser/session state is not a database seed prerequisite.
Different scenarios may need different preconditions. Seed their distinct prerequisite
objects with the exact specified identities; scenario-specific absence, counts or mutable
states can still be arranged by isolated test fixtures. If constraints prevent coexistence,
keep the shared baseline valid and leave conflicting scenario variations to test setup.
Return tool_calls=[] only when no prerequisite rows need adding or correcting.

Read relevant existing insertion SQL, then append missing rows or replace a small exact
span. Preserve ALL earlier requirements' records and comments; never replace a whole
file or rebuild it for only the current requirement. Mark related statements with the
requirement ID. A table's insertion file inserts only into that table; put its parents
and associations in their own files. SELECT subqueries may resolve existing foreign keys.
Use stable identifiers/business keys and SQLite INSERT ... SELECT ... WHERE NOT EXISTS,
or a targeted ON CONFLICT ... DO NOTHING. Avoid INSERT OR IGNORE, which hides invalid data.
Repeated startup must not duplicate records, overwrite user edits or reset credentials.
Do not DELETE, DROP, REPLACE, change table definitions, disable constraints or suppress errors.
The loader executes these files in table-dependency order inside the initialization
transaction; foreign-key checks are deferred until all seed files have executed.

For password-hash columns, use the SQL function seed_password_hash('required password').
It returns scrypt$saltHex$digestHex using a 16-byte salt and a 64-byte digest, compatible
with the documented test credential format. Never store a plaintext password in a hash
column or invent a digest. The password function is called by SQL only for missing rows.
Escape SQL literals correctly; use 0/1 booleans and valid JSON text when required.
Real initialization/build checks run after this pass and the database owner repairs errors.
'''


def implement_startup_data(arc_dir, schema, model, console, failures, max_turns=10):
    """Create per-table files, then accumulate prerequisite rows one requirement at a time."""
    output = arc_dir.parent.resolve()
    order = [name for group in implementation_groups(schema) for name in group]
    insert_paths = {name: f"backend/src/db/seeds/{name}.sql" for name in order}
    for name, relative in insert_paths.items():
        if not (output / relative).is_file():
            save_text(output / relative, f"-- Prerequisite rows for {name}; extended incrementally by requirement.\n")
    save_text(output / SEED_PATH, seed_source(order))
    checkpoint(output, stage="05", task="startup data loader", action="Publish per-table insertion files and loader",
        details={"insertion_order": order, "insert_files": insert_paths})

    tree = RequirementTree(read_artifact(arc_dir, "requirements.json"))
    dependencies = table_dependencies(schema)
    allowed = set(insert_paths.values())
    readable = allowed | {f"backend/src/db/tables/{name}.sql" for name in order}
    for rid in tree.leaves:
        requirement = requirement_context(tree, rid)
        if not requirement["description"] and not requirement["steps"]:
            continue
        with failures.task("startup data / " + rid):
            names = set()
            for symbol in schema["requirements"].get(rid, []):
                names.add(symbol.split(".", 1)[0])
            pending = list(names)
            while pending:
                for parent in dependencies[pending.pop()]:
                    if parent not in names:
                        names.add(parent)
                        pending.append(parent)
            entities = {name: schema["entities"][name] for name in sorted(names)}
            references = [f"backend/src/db/tables/{name}.sql" for name in entities
                if (output / f"backend/src/db/tables/{name}.sql").is_file()]
            references.extend(insert_paths[name] for name in sorted(names))
            files = FileTools(output, references=references, allow_write=lambda path: path in allowed,
                readable=readable)
            task = {"requirement": requirement, "entities": entities, "table_names": order,
                "insert_files": {name: insert_paths[name] for name in sorted(names)}}

            def generated():
                return {"status": "GENERATED", "insert_files": list(files.changed_paths)}

            run_file_agent(model, SEED_INSTRUCTIONS, task, files, generated,
                max_turns, console, "Startup data / " + rid, allow_discovery=False)


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
    insert_paths = {name: f"backend/src/db/seeds/{name}.sql" for name in schema["entities"]}
    allowed = {*WIRING, *sql_paths.values(), *insert_paths.values()}
    workspace = FileTools(output, WIRING, allow_write=lambda path: path in allowed, readable=allowed)
    task = {"table_order": [name for group in implementation_groups(schema) for name in group],
        "startup_data_loader": SEED_PATH,
        "insertion_directory": "backend/src/db/seeds",
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
        workspace.files = set(WIRING) | {sql_paths[name] for name in selected} | {insert_paths[name] for name in selected}
        workspace.writable = set(workspace.files)
        task["entities"] = {name: schema["entities"][name] for name in sorted(selected)}
        return value

    try:
        agent = run_file_agent(model or TextModel(), REPAIR_INSTRUCTIONS, task, workspace, gate,
            max_turns, console, "Database runtime repair", feedback=feedback,
            feedback_filter=repair_feedback, allow_discovery=False)
        report.update(status="GREEN", repair_turns=agent["turns"])
        save_json(path, report)
        return report
    except (ValueError, RuntimeError) as error:
        report.update(status="FAILED", repair_turns=getattr(error, "turns", 0), error=str(error))
        save_json(path, report)
        raise
