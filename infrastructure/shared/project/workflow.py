"""Step 00: initialize the application workspace for the selected technology stack."""

from pathlib import Path

from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.shared.project.initialize import DEFAULT_STACK, STACKS, initialize_project


def project_initialization(output_dir: Path, pause: bool = False, stack: str = DEFAULT_STACK,
        *, port: int = 3000) -> list[str]:
    created = initialize_project(output_dir, stack, port=port)
    DemoConsole(pause).show(
        f"Project initialization | {stack}",
        "\n".join(created) or "Project files already exist; no files replaced.",
    )
    print(f"Project initialized: {output_dir}", flush=True)
    return created
