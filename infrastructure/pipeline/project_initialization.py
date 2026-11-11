"""Step 00: initialize the application workspace for the selected technology stack."""

from pathlib import Path
import shutil

from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.shared.project.initialize import DEFAULT_STACK, initialize_project
from infrastructure.shared.project.git import initialize_repository, checkpoint


def project_initialization(input_dir: Path, output_dir: Path, pause: bool = False, stack: str = DEFAULT_STACK, port: int = 3000) -> list[str]:
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    if input_dir != output_dir:
        if output_dir.is_relative_to(input_dir):
            raise ValueError("Output directory must not be inside the requirements directory")
        
        # copy requirements directory to output directory, ignoring tests
        shutil.copytree(input_dir, output_dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns("tests"))

    initialize_repository(output_dir)
    created = initialize_project(output_dir, stack, port)
    checkpoint(output_dir, stage="00", task="project", action="Publish application scaffold",
        details={"stack": stack, "port": port, "created_files": created})
    DemoConsole(pause).show(
        f"Project initialization | {stack}",
        "\n".join(created) or "Project files already exist; no files replaced.",
    )
    print(f"Project initialized: {output_dir}", flush=True)
    return created
