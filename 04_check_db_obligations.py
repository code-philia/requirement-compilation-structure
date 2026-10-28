"""Step 04: validate obligation records and schema references without changing effects."""

from contextlib import ExitStack
from pathlib import Path

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.stages.database.obligations.records import field_symbols, validate_obligations
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.database.schema import validate_schema
from infrastructure.utils.files import read_artifact, save_json


def check_db_obligations(arc_dir: Path, pause: bool = False) -> dict:
    """Validate node IDs and field symbols, preserving each node's inferred read/write sets."""
    tree = RequirementTree(read_artifact(arc_dir, "requirements.json"))
    schema = read_artifact(arc_dir, "db_schema.json")
    validate_schema(schema)
    # This boundary checks representation and references only. Requirement,
    # child, and step effects remain independent; no containment is enforced.
    result = validate_obligations(
        read_artifact(arc_dir, "db_obligations.json"), tree, field_symbols(schema),
    )
    save_json(arc_dir / "db_obligations_checked.json", result)
    DemoConsole(pause).show("Step 04 | Obligation records validated", (
        f"Requirements: {len(result['requirements'])}\nSteps: {len(result['steps'])}\n"
        "Node IDs and schema field references are valid. Inferred effects are preserved.\n"
        f"Saved: {arc_dir / 'db_obligations_checked.json'}"
    ))
    return result


def main() -> None:
    """Run obligation record validation using the shared CLI and workspace log."""
    parser = create_parser("Step 04: Validate DB Obligation Records")
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
