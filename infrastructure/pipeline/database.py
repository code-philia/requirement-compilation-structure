"""Step 04: implement tables, per-table prerequisite inserts and real initialization."""

import json
from pathlib import Path

from infrastructure.stages.database.order import implementation_groups, table_dependencies
from infrastructure.stages.database.runtime import initializer_source
from infrastructure.stages.database.implementation_agent import DatabaseImplementationAgent
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.formatting import format_schema
from infrastructure.shared.agent.tools.file_tools import NativeFileTools
from infrastructure.shared.agent.tasks import TaskFailures
from infrastructure.utils.files import save_text
from infrastructure.shared.project.git import checkpoint
from infrastructure.stages.database.implementation import implement_startup_data, verify_database_runtime
from infrastructure.utils.files import read_source


def implement_db(arc_dir: Path, pause: bool = False) -> dict:
    source = arc_dir / "db_schema.json"
    if not source.is_file():
        raise ValueError("Run main.py --stage 02 first to create .arc/db_schema.json")
    output_dir = arc_dir.parent.resolve()
    for required in ("backend/package.json", "backend/src/db/client.ts", "backend/src/db/initialize.ts"):
        if not (output_dir / required).is_file():
            raise ValueError("Run main.py --stage 00 first to initialize the project structure")
    schema = json.loads(source.read_text(encoding="utf-8-sig"))
    console = DemoConsole(pause)
    # --- Extension point 04B: dependency-aware table implementation -----------
    # Referenced tables precede dependents. Cyclic groups use forward references;
    # available implementations and unresolved target definitions remain explicit.
    groups = implementation_groups(schema)
    order = [name for group in groups for name in group]
    dependencies = table_dependencies(schema)
    print("Table implementation order: " + (" -> ".join(order) or "(No tables.)"), flush=True)
    implementations = {}
    failures = TaskFailures(arc_dir, "04_implement_db", console)
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
                # --- Extension point 04C: generation context and correction -------
                expected_path = f"backend/src/db/tables/{name}.sql"
                request = {
                    "entity_name": name, "entity": entity, "output_path": expected_path,
                    "referenced_tables": referenced,
                }
                requirement_ids = [rid for rid, fields in schema["requirements"].items()
                    if any(field.split(".", 1)[0] == name for field in fields)]
                tools = NativeFileTools(output_dir, requirements=requirement_ids,
                    stage="database", writable=[expected_path],
                    readable=[f"backend/src/db/tables/{entity}.sql" for entity in order])

                agent = DatabaseImplementationAgent("table")
                try:
                    agent.run(request, tools)
                finally:
                    agent.model.client.close()
                checkpoint(output_dir, stage="04", task=name, action="Publish table SQL",
                    details={"path": expected_path})
                content = read_source(output_dir / expected_path)
                proposal = {"path": expected_path, "content": content}
                target = output_dir / expected_path
                implementations[name] = proposal
                console.show(f"{label} | 4. Table implementation saved", (
                    f"{target}\n\nSQL proposal saved. The compiler runs fixed initialization and startup checks next."
                    + "\nValue CHECK constraints and application-only rules remain available for semantic review."
                ))
    # --- Pass boundary: wire generated SQL, then execute initialization ----------
    # The executable loader is the order registry; no extra manifest is retained.
    initializer = output_dir / "backend/src/db/initialize.ts"
    if not initializer.resolve().is_relative_to(output_dir):
        raise ValueError("DB initializer path escapes the output directory")
    save_text(initializer, initializer_source(implementations))
    checkpoint(output_dir, stage="04", task="database initializer", action="Publish ordered SQL initialization",
        details={"table_order": order, "published_tables": list(implementations)})
    print(f"Database initialization wired: {initializer}", flush=True)
    if order:
        # Revisit requirements after DDL: preserve and extend each table's prerequisite rows.
        implement_startup_data(arc_dir, schema, console, failures)
    with failures.task("database runtime"):
        verified = verify_database_runtime(arc_dir, schema, console)
        console.show("Database runtime | GREEN", json.dumps(verified, ensure_ascii=False, indent=2))
    failures.finish()
    return implementations
