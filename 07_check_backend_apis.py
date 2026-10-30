"""Step 07: display complete backend API definitions and requirement associations."""

from contextlib import ExitStack
import json
from pathlib import Path

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.files import read_artifact
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log


def check_backend_apis(arc_dir: Path, pause: bool = False) -> dict:
    """Read and print the API artifact without changing it or validating its design."""
    design = read_artifact(arc_dir, "backend_apis.json")
    DemoConsole(pause).show("Step 07 | Backend API design", json.dumps(design, ensure_ascii=False, indent=2))
    return design


def main() -> None:
    parser = create_parser("Step 07: Display Backend APIs")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            check_backend_apis(output_dir / ".arc", args.pause)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
