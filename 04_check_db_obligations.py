"""Step 04: validate obligation records and schema references without changing effects."""

from contextlib import ExitStack
from pathlib import Path

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.stages.database.obligations.records import field_symbols, validate_obligations
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.database.schema import validate_schema
from infrastructure.utils.files import read_artifact
from infrastructure.utils.presentation.formatting import format_obligations, format_requirement_schema_relations


def check_db_obligations(arc_dir: Path, pause: bool = False) -> dict:
    """Print the schema ER graph and requirement-to-field/read-write relations."""
    tree = RequirementTree(read_artifact(arc_dir, "requirements.json"))
    schema = read_artifact(arc_dir, "db_schema.json")
    validate_schema(schema)
    result = validate_obligations(read_artifact(arc_dir, "db_obligations.json"), tree, field_symbols(schema))
    DemoConsole(pause).show("Step 04 | Obligation records validated", (
        format_requirement_schema_relations(schema) + "\n\nOBLIGATIONS\n" +
        format_obligations(result["requirements"]) + "\nSTEPS\n" + format_obligations(result["steps"])
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
