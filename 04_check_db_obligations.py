"""Step 04: check containment and propagate obligations upward using rules only."""

import json
from contextlib import ExitStack
from pathlib import Path

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.stages.database.obligations.records import field_symbols, validate_obligations
from infrastructure.stages.database.obligations.rules import difference, propagate_obligations
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.presentation.formatting import format_obligations, format_todos
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.database.schema import validate_schema
from infrastructure.utils.files import save_json


def check_db_obligations(arc_dir: Path, pause: bool = False) -> dict:
    for filename, previous in (
        ("requirements.json", "01_explore_requirement.py"),
        ("db_schema.json", "02_build_db_schema.py"),
        ("db_obligations.json", "03_infer_db_obligations.py"),
    ):
        if not (arc_dir / filename).is_file():
            raise ValueError(f"Run {previous} first to create .arc/{filename}")
    tree = RequirementTree(json.loads((arc_dir / "requirements.json").read_text(encoding="utf-8")))
    schema = json.loads((arc_dir / "db_schema.json").read_text(encoding="utf-8"))
    validate_schema(schema)
    # --- Validation boundary: resolve every node and field --------------------
    # A missing node or unknown field is an input error, not a coverage gap.
    # Keep symbol/ID validation separate from the propagation policy below.
    obligations = validate_obligations(
        json.loads((arc_dir / "db_obligations.json").read_text(encoding="utf-8")), tree, field_symbols(schema),
    )
    console = DemoConsole(pause)
    order = {rid: index for index, rid in enumerate(tree.postorder, 1)}

    # --- Extension point 04A: explain each rule application --------------------
    # This callback only presents results. Rewrite it for alternative classroom
    # views without changing the rule engine or its deterministic traversal.
    def show_node(rid, before, after, sources, todos):
        label = f"{order[rid]}/{len(order)} {rid}"
        console.show(f"{label} | 1. Current obligations (before)", (
            tree.requirements[rid]["name"] + "\n\n" + format_obligations({rid: before})
        ))
        console.show(f"{label} | 2. Lower-level obligations", (
            "Own steps:\n" + format_obligations(sources["steps"])
            + "\nDirect children (already processed):\n" + format_obligations(sources["children"])
        ))
        console.show(f"{label} | 3. Upward additions and result", (
            "Newly added obligations:\n" + format_obligations({rid: difference(after, before)}, empty_label="No additions needed")
            + "\nResult:\n" + format_obligations({rid: after})
        ))
        console.show(f"{label} | 4. Containment coverage", format_todos(todos))

    # --- Key extension point 04B: propagation and coverage rules ---------------
    # Implementation: infrastructure/stages/database/obligations/rules.py. Current policy is
    # postorder, upward-only union, with unresolved downward gaps as TODOs.
    # Try a different policy there; retain separate reads/writes and report
    # unresolved gaps rather than claiming that propagation proves coverage.
    result = propagate_obligations(tree, obligations, on_node=show_node)
    # Keep the checked result separate for comparison with the raw predictions.
    save_json(arc_dir / "db_obligations_checked.json", result)
    print(f"Checked obligations saved: {arc_dir / 'db_obligations_checked.json'}", flush=True)
    print(f"Bottom-up propagation completed. Unresolved coverage TODOs: {len(result['todos'])}.")
    print("TODO: Downward allocation is not implemented; review uncovered fields before assigning them to children or steps.")
    return result


def main() -> None:
    parser = create_parser("Step 04: Check and Propagate DB Obligations")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir))
            check_db_obligations(output_dir / ".arc", args.pause)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
