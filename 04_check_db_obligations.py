"""Step 04: validate obligation records and schema references without changing effects. CLI wrapper."""

from contextlib import ExitStack

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log
from infrastructure.stages.database.obligations.review import check_db_obligations


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
