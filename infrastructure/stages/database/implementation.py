"""Repair generated DDL and startup wiring against actual application execution."""

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
from infrastructure.utils.files import save_json


WIRING = (
    "backend/src/db/client.ts", "backend/src/db/initialize.ts", "backend/src/db/setup.ts",
    "backend/src/server.ts", "backend/src/app.ts", "backend/src/api/register.ts",
    "backend/scripts/copy-db.mjs", "package.json", "backend/package.json", "backend/tsconfig.json",
)

REPAIR_INSTRUCTIONS = '''Repair the actual database implementation and its startup wiring.
The compiler has already generated SQL and executed real checks; feedback contains
actual build, SQLite initialization or server startup failures. Use edit_file for repairs.

Use the canonical schema as authority. Repair the responsible SQL table files, related
foreign-key tables, initializer, client, setup/server entry point or SQL build-copy wiring.
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
