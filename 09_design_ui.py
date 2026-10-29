"""Step 09: design all leaf requirements' UI/data without implementing pages. CLI wrapper."""

from contextlib import ExitStack

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log
from infrastructure.stages.frontend.ui.design_stage import design_frontend_ui


def main() -> None:
    parser = create_parser("Step 09: UI/data Design with Page RAG")
    parser.add_argument("--top-k", type=int, default=3, help="Number of coarse page RAG candidates")
    parser.add_argument("--max-fixtures", type=int, default=3, help="Maximum named display states per page; compiler-owned default is free")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir))
            design_frontend_ui(input_dir, output_dir / ".arc", args.pause, args.top_k, args.max_fixtures)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
