"""Step 06: decompose APIs, allocate obligations, and design fixed I/O interfaces. CLI wrapper."""

from contextlib import ExitStack

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log
from infrastructure.stages.backend.decomposition import decompose_backend_apis


def main() -> None:
    parser = create_parser("Step 06: Backend API Decomposition / Obligation Propagation")
    parser.add_argument("--top-k", type=int, default=6, help="Number of API retrieval hits")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output = resolve_directories(args)
            stack.enter_context(console_log(output))
            decompose_backend_apis(output / ".arc", args.pause, args.top_k)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
