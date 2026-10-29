"""Step 07: infer P/Q conditions over fixed API interfaces and obligations. CLI wrapper."""

from contextlib import ExitStack

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log
from infrastructure.stages.backend.contract_inference import infer_api_contracts


def main() -> None:
    parser = create_parser("Step 07: Backend API Contract Inference")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output = resolve_directories(args)
            stack.enter_context(console_log(output))
            infer_api_contracts(output / ".arc", args.pause)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
