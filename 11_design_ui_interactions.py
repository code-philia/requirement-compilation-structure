"""Step 11: Trigger/event Decomposition, Obligation Propagation, and Contract Inference. CLI wrapper."""

from contextlib import ExitStack

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log
from infrastructure.stages.frontend.interactions.design_stage import design_ui_interactions


def main() -> None:
    parser = create_parser("Step 11: UI Interaction Design and Contract Inference")
    parser.add_argument("--max-attempts", type=int, default=3,
        help="Maximum proposals per decomposition or event contract; 0 retries until valid (default: 3)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir))
            design_ui_interactions(input_dir, output_dir / ".arc", args.pause, args.max_attempts)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
