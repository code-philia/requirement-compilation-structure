"""Step 08: TDD-driven enforcement of P, Q, and Dataflow Obligations. CLI wrapper."""

from contextlib import ExitStack

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log
from infrastructure.stages.backend.implementation import implement_backend_tdd


def main() -> None:
    parser = create_parser("Step 08: TDD-driven API Implementation (P / Q / Dataflow Obligations)")
    parser.add_argument("--max-turns", type=int, default=18, help="Maximum edit rounds per test/implementation agent")
    parser.add_argument("--max-tests", type=int, default=5, help="Maximum key contract tests per API (default: 5)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output = resolve_directories(args)
            stack.enter_context(console_log(output))
            implement_backend_tdd(output / ".arc", args.pause, args.max_turns, args.max_tests)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
