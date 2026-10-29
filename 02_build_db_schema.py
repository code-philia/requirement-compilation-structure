"""Step 02: discover entities and fields incrementally using schema RAG. CLI wrapper."""

from contextlib import ExitStack

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log
from infrastructure.stages.database.schema_synthesis import build_db_schema


def main() -> None:
    parser = create_parser("Step 02: Build DB Schema with RAG")
    parser.add_argument("--top-k", type=int, default=6, help="Number of BM25 entity/field hits (default: 6)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir))
            build_db_schema(output_dir / ".arc", args.pause, args.top_k)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
