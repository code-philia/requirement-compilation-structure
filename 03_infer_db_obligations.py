"""Step 03: infer database read/write obligations for every requirement and step. CLI wrapper."""

from contextlib import ExitStack

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log
from infrastructure.stages.database.obligations.inference import infer_db_obligations


def main() -> None:
    parser = create_parser("Step 03: Infer DB Obligations")
    parser.add_argument("--top-k", type=int, default=6, help="Number of BM25 entity/field hits (default: 6)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir))
            infer_db_obligations(output_dir / ".arc", args.pause, args.top_k)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
