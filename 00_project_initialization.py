"""Step 00: initialize the application workspace for the selected technology stack."""

from contextlib import ExitStack
from pathlib import Path

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.shared.project.initialize import DEFAULT_STACK, STACKS, initialize_project


def project_initialization(output_dir: Path, pause: bool = False, stack: str = DEFAULT_STACK) -> list[str]:
    created = initialize_project(output_dir, stack)
    DemoConsole(pause).show(
        f"Project initialization | {stack}",
        "\n".join(created) or "Project files already exist; no files replaced.",
    )
    print(f"Project initialized: {output_dir}", flush=True)
    return created


def main() -> None:
    parser = create_parser("Step 00: Project Initialization")
    parser.add_argument("--stack", choices=sorted(STACKS), default=DEFAULT_STACK, help="Technology stack; extend STACKS to register another template")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir))
            project_initialization(output_dir, args.pause, args.stack)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
