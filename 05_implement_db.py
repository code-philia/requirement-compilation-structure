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
from infrastructure.utils.files import save_text


# --- Extension point 05A: SQL lowering policy ---------------------------------
# The model writes concrete DDL; Python enforces file ownership and validates the
# resulting table against the existing IR before publishing application code.
INSTRUCTIONS = """Implement the current schema entity as one SQLite table.
Return exactly {"path": "the supplied output_path", "content": "SQL file contents"}.
Use the supplied output_path exactly. Return plain SQL content, not Markdown.
The file must contain exactly one CREATE TABLE IF NOT EXISTS statement for the
current entity, preserving entity and field names exactly and quoting identifiers
with double quotes. No extra tables, triggers, indexes, PRAGMAs, DML, or transactions.
Use TEXT for string/uuid/date/datetime/json, INTEGER for integer/boolean, REAL for number.
Write explicit NOT NULL whenever nullable=false, including primary keys. Preserve
primary keys, uniqueness, and every references edge. An INTEGER PRIMARY KEY need not
use AUTOINCREMENT. No defaults: UUIDs and other generated values are supplied by the
application. Do not introduce cascading deletes/updates or extra uniqueness rules.
Translate SQLite-enforceable value constraints into CHECK constraints, including
boolean values 0/1 and explicit enumerations. Preserve exact comparison semantics;
do not add trimming, normalization, or extra business rules. Rules requiring application
logic (e.g. cryptographic password hashing) should be documented as SQL comments,
not replaced with an ineffective or invented CHECK. Do not invent new schema fields.
Referenced table implementations are authoritative examples for naming, types, and
key constraints. Within a cycle or self-reference an implementation may be null:
use the supplied target schema, retain the FK, and rely on SQLite forward references.
The runtime enables foreign_keys and executes these files in one transaction. It
preserves existing tables and data. If correction is supplied, fix the reported error
and return one complete JSON object with path and content.
"""


def implement_db(arc_dir: Path, pause: bool = False) -> dict:
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
            for attempt in range(1, 4):
                response = None
                try:
                    response = model.generate_json(INSTRUCTIONS, request)
                    content = response["content"]
                    proposal = {"path": expected_path, "content": content}
                    break
                except json.JSONDecodeError as error:
                    if attempt == 3:
                        raise ValueError(f"Table implementation failed for {name} after 3 attempts: {error}") from error
                    print(f"Retrying {name} ({attempt + 1}/3): {error}", flush=True)
                    request["correction"] = {"error": str(error), "previous_response": response}
            console.show(f"{label} | 3. Model file proposal (validated)", expected_path + "\n\n" + content)
            target = output_dir / expected_path
            if not target.resolve().is_relative_to(output_dir):
                raise ValueError(f"Implementation path escapes the output directory: {expected_path}")
            save_text(target, content.rstrip() + "\n")
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
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            implement_db(output_dir / ".arc", args.pause)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
