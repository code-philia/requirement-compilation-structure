"""Step 12: implement UI interactions through real-application Playwright E2E TDD. CLI wrapper."""

from contextlib import ExitStack

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log
from infrastructure.stages.frontend.interactions.implementation_stage import implement_frontend_interactions


def main() -> None:
    parser = create_parser("Step 12: UI Interaction Implementation through Playwright E2E TDD")
    parser.add_argument("--max-turns", type=int, default=18, help="Maximum edit rounds per requirement's test/implementation agent")
    parser.add_argument("--max-tests", type=int, default=5, help="Maximum key E2E cases per requirement")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir))
            implement_frontend_interactions(input_dir, output_dir / ".arc", args.pause, args.max_turns, args.max_tests)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
