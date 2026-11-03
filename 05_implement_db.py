"""Step 05: implement tables, per-table prerequisite inserts and real initialization."""

import json
from contextlib import ExitStack
from pathlib import Path

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.stages.database.order import implementation_groups, table_dependencies
from infrastructure.stages.database.runtime import initializer_source
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.formatting import format_schema
from infrastructure.utils.presentation.logging import console_log
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.tasks import TaskFailures
from infrastructure.utils.files import save_text
from infrastructure.shared.project.git import checkpoint
from infrastructure.stages.database.implementation import implement_startup_data, verify_database_runtime
from infrastructure.utils.files import read_source


# --- Extension point 05A: SQL lowering policy ---------------------------------
# The model writes DDL through the shared edit_file tool at the supplied table path.
# The real initializer and compiled startup are checked and repaired in this pass.
INSTRUCTIONS = """Implement entity as SQLite DDL for the compiler-selected output_path.
Use edit_file to create output_path under backend/src/db/tables, or replace exact
existing SQL when rerunning. This task owns this one fixed SQL path. Read the supplied
related SQL first; use read_file only for missing relevant evidence. The compiler adapts
an unambiguous misplaced creation to output_path and reports the actual path.

Create the current entity with CREATE TABLE IF NOT EXISTS, preserving its entity and
field names and quoting identifiers with double quotes. Implement the supplied keys,
nullability, uniqueness, references and SQLite-enforceable value constraints.
Map string/uuid/date/datetime/json to TEXT, integer/boolean to INTEGER, number to REAL.
Use explicit NOT NULL when nullable=false. SQLite INTEGER PRIMARY KEY can generate
its value; application code supplies other generated values unless schema evidence
specifies otherwise. Do not invent defaults, normalization, cascades or uniqueness.

Use CHECK for enforceable constraints such as boolean 0/1 or enumerations. Describe
application-only rules such as password hashing in comments instead of inventing SQL
checks. SQLite CHECK expressions must not contain subqueries, SELECT, EXISTS,
aggregates or window functions. For JSON arrays, use scalar checks such as
json_valid(field) and json_type(field) = 'array'; validate array element types in
application code, not with json_each subqueries inside CHECK. Keep constraints
requiring multi-row or cross-table inspection in application code.
This task creates one table, without extra tables, data mutations or application startup code.
referenced_tables provides target definitions and available SQL. A null implementation
means the target has not been generated yet; SQLite forward references can express
self-references and cycles. The initializer enables foreign keys and runs the ordered
SQL files in a transaction. Preserve existing data through IF NOT EXISTS.
"""


def implement_db(arc_dir: Path, pause: bool = False, max_attempts: int = 10, max_turns: int = 10) -> dict:
    if max_turns < 1:
        raise ValueError("--max-turns must be positive")
    source = arc_dir / "db_schema.json"
    if not source.is_file():
        raise ValueError("Run 02_build_db_schema.py first to create .arc/db_schema.json")
    output_dir = arc_dir.parent.resolve()
    for required in ("backend/package.json", "backend/src/db/client.ts", "backend/src/db/initialize.ts"):
        if not (output_dir / required).is_file():
            raise ValueError("Run 00_project_initialization.py first to initialize the project structure")
    schema = json.loads(source.read_text(encoding="utf-8-sig"))
    console = DemoConsole(pause)
    # --- Extension point 05B: dependency-aware table implementation -----------
    # Referenced tables precede dependents. Cyclic groups use forward references;
    # available implementations and unresolved target definitions remain explicit.
    groups = implementation_groups(schema)
    order = [name for group in groups for name in group]
    dependencies = table_dependencies(schema)
    print("Table implementation order: " + (" -> ".join(order) or "(No tables.)"), flush=True)
    model = TextModel() if order else None
    implementations = {}
    failures = TaskFailures(arc_dir, "05_implement_db", console)
    for group in groups:
        for name in group:
            with failures.task(name):
                entity = schema["entities"][name]
                label = f"{len(implementations) + 1}/{len(order)} {name}"
                cycle = len(group) > 1 or name in dependencies[name]
                console.show(f"{label} | 1. Table and dependency plan", (
                    "Order: " + " -> ".join(order)
                    + "\nReferences: " + (", ".join(dependencies[name]) or "(none)")
                    + ("\nCyclic group (SQLite forward references): " + ", ".join(group) if cycle else "")
                    + "\n\n" + format_schema({name: entity})
                ))
                referenced = {
                    target: {"schema": schema["entities"][target], "implementation": implementations.get(target)}
                    for target in dependencies[name]
                }
                console.show(f"{label} | 2. Referenced table implementations", (
                    "\n\n".join(
                        f"{target}:\n" + (item["implementation"]["path"] + "\n" + item["implementation"]["content"]
                        if item["implementation"] else "Not implemented yet; target schema is supplied for the forward reference.\n" + format_schema({target: item["schema"]}))
                        for target, item in referenced.items()
                    ) or "(No referenced tables.)"
                ))
                # --- Extension point 05C: generation context and correction -------
                expected_path = f"backend/src/db/tables/{name}.sql"
                request = {
                    "entity_name": name, "entity": entity, "output_path": expected_path,
                    "referenced_tables": {target: {**record, "implementation":
                        {"path": record["implementation"]["path"]} if record["implementation"] else None}
                        for target, record in referenced.items()},
                }
                related_files = [f"backend/src/db/tables/{target}.sql" for target in dependencies[name]
                    if (output_dir / f"backend/src/db/tables/{target}.sql").is_file()]
                tools = FileTools.for_target(output_dir, "db", name, fixed_path=expected_path,
                    references=related_files,
                    readable=[f"backend/src/db/tables/{entity}.sql" for entity in order])

                def generated_table():
                    if not (output_dir / expected_path).is_file():
                        raise ValueError("Create the current SQL output_path with edit_file")
                    return {"path": expected_path, "status": "GENERATED"}

                run_file_agent(model, INSTRUCTIONS, request, tools, generated_table,
                    max_attempts, console, f"SQL implementation {name}", allow_discovery=False)
                content = read_source(output_dir / expected_path)
                proposal = {"path": expected_path, "content": content}
                target = output_dir / expected_path
                implementations[name] = proposal
                console.show(f"{label} | 4. Table implementation saved", (
                    f"{target}\n\nSQL proposal saved. This pass checks real initialization and startup next."
                    + "\nValue CHECK constraints and application-only rules remain available for semantic review."
                ))
    # --- Pass boundary: wire candidates, then execute and repair them ----------
    # The executable loader is the order registry; no extra manifest is retained.
    initializer = output_dir / "backend/src/db/initialize.ts"
    if not initializer.resolve().is_relative_to(output_dir):
        raise ValueError("DB initializer path escapes the output directory")
    save_text(initializer, initializer_source(implementations))
    checkpoint(output_dir, stage="05", task="database initializer", action="Publish ordered SQL initialization",
        details={"table_order": order, "published_tables": list(implementations)})
    print(f"Database initialization wired: {initializer}", flush=True)
    if order:
        # Revisit requirements after DDL: preserve and extend each table's prerequisite rows.
        implement_startup_data(arc_dir, schema, model, console, failures, max_attempts)
    with failures.task("database runtime"):
        verified = verify_database_runtime(arc_dir, schema, model, console, max_turns)
        # The runtime owner can repair tables whose initial generation failed.
        for name in order:
            relative = f"backend/src/db/tables/{name}.sql"
            implementations[name] = {"path": relative, "content": read_source(output_dir / relative)}
            entry = failures.report["tasks"].get(name)
            if entry and entry["status"] == "FAILED":
                failures.report["tasks"][name] = {"status": "GREEN", "initial_failure": entry,
                    "recovered_by": "database runtime repair"}
        console.show("Database runtime | GREEN", json.dumps(verified, ensure_ascii=False, indent=2))
    failures.finish()
    return implementations


def main() -> None:
    parser = create_parser("Step 05: Implement DB Tables and Required Startup Data")
    parser.add_argument("--max-attempts", type=int, default=10, help="Maximum proposals per table or startup-data requirement (default: 10)")
    parser.add_argument("--max-turns", type=int, default=10, help="Maximum real database/startup repair rounds")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            implement_db(output_dir / ".arc", args.pause, args.max_attempts, args.max_turns)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
