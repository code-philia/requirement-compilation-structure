"""Step 05: implement one SQLite CREATE TABLE file per schema entity."""

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
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.utils.files import save_text


# --- Extension point 05A: SQL lowering policy ---------------------------------
# The model writes DDL; Python publishes it at the supplied table path.
# Executable behavior is exercised by later application tests.
INSTRUCTIONS = """Implement entity as SQLite DDL for the compiler-selected output_path.
Return {"content": "complete SQL file contents"}. The compiler writes output_path.
The content string contains SQL text without Markdown fences.

Create the current entity with CREATE TABLE IF NOT EXISTS, preserving its entity and
field names and quoting identifiers with double quotes. Implement the supplied keys,
nullability, uniqueness, references and SQLite-enforceable value constraints.
Map string/uuid/date/datetime/json to TEXT, integer/boolean to INTEGER, number to REAL.
Use explicit NOT NULL when nullable=false. SQLite INTEGER PRIMARY KEY can generate
its value; application code supplies other generated values unless schema evidence
specifies otherwise. Do not invent defaults, normalization, cascades or uniqueness.

Use CHECK for enforceable constraints such as boolean 0/1 or enumerations. Describe
application-only rules such as password hashing in comments instead of inventing SQL
checks. This task creates one table, without extra tables, data mutations or application startup code.
referenced_tables provides target definitions and available SQL. A null implementation
means the target has not been generated yet; SQLite forward references can express
self-references and cycles. The initializer enables foreign keys and runs the ordered
SQL files in a transaction. Preserve existing data through IF NOT EXISTS.
"""


def implement_db(arc_dir: Path, pause: bool = False, max_attempts: int = 10) -> dict:
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
    for group in groups:
        for name in group:
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
                "referenced_tables": referenced,
            }
            content, _ = propose_json(model, INSTRUCTIONS, request,
                lambda response: response["content"].rstrip() + "\n", console,
                f"SQL implementation {name}", max_attempts)
            proposal = {"path": expected_path, "content": content}
            console.show(f"{label} | 3. Model file proposal", expected_path + "\n\n" + content)
            target = output_dir / expected_path
            if not target.resolve().is_relative_to(output_dir):
                raise ValueError(f"Implementation path escapes the output directory: {expected_path}")
            save_text(target, content)
            implementations[name] = proposal
            console.show(f"{label} | 4. Table implementation saved", (
                f"{target}\n\nSQL proposal saved. Executable behavior is checked by application tests."
                + "\nValue CHECK constraints and application-only rules remain available for semantic review."
            ))
    # --- Pass boundary: activate only a completely validated table set --------
    # The executable loader is the order registry; no extra manifest is retained.
    initializer = output_dir / "backend/src/db/initialize.ts"
    if not initializer.resolve().is_relative_to(output_dir):
        raise ValueError("DB initializer path escapes the output directory")
    save_text(initializer, initializer_source(implementations))
    print(f"Database initialization wired: {initializer}", flush=True)
    return implementations


def main() -> None:
    parser = create_parser("Step 05: Implement DB Tables")
    parser.add_argument("--max-attempts", type=int, default=10, help="Maximum proposals per table; including the first proposal (default: 10)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            implement_db(output_dir / ".arc", args.pause, args.max_attempts)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
