"""Run tutorial steps 00 through 12 sequentially without teaching pauses."""

import argparse
from pathlib import Path
import subprocess
import sys

from infrastructure.utils.cli import COMPILER_DIR, resolve_directories
from infrastructure.utils.processes import start_process, stop_process
from infrastructure.utils.presentation.logging import configure_console
from infrastructure.utils.presentation.console import show_panel
from infrastructure.utils.presentation.stages import stage_label


STEPS = (
    "00_project_initialization.py",
    "01_explore_requirement.py",
    "02_build_db_schema.py",
    "03_infer_db_obligations.py",
    "05_implement_db.py",
    "06_decompose_backend_apis.py",
    "07_infer_api_contracts.py",
    "08_implement_backend_tdd.py",
    "09_design_ui.py",
    "10_implement_ui.py",
    "11_design_ui_interactions.py",
    "12_implement_frontend_tdd.py",
)


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=COMPILER_DIR / "input", help="Requirement/image directory")
    parser.add_argument("--output", type=Path, required=True, help="Shared output directory for all steps")
    args = parser.parse_args()
    try:
        input_dir, output_dir = resolve_directories(args)
        if not input_dir.is_dir():
            raise ValueError(f"Input directory does not exist: {input_dir}")
        show_panel("Requirement compiler | Pipeline", f"Input: {input_dir}\nOutput: {output_dir}\nStages to run: {len(STEPS)}")
        for index, step in enumerate(STEPS, 1):
            show_panel(f"[{index}/{len(STEPS)}] {stage_label(step)}", f"Running {step}")
            process = start_process(
                [sys.executable, str(COMPILER_DIR / step), "--input", str(input_dir), "--output", str(output_dir)],
                cwd=COMPILER_DIR,
            )
            try:
                code = process.wait()
            except BaseException:
                stop_process(process)
                raise
            if code:
                raise subprocess.CalledProcessError(code, [sys.executable, step])
    except subprocess.CalledProcessError as error:
        parser.exit(error.returncode if error.returncode > 0 else 1, f"Pipeline stopped: {step} failed.\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Execution failed: {error}\n")
    except KeyboardInterrupt:
        parser.exit(130, "Pipeline interrupted.\n")
    show_panel("[DONE] All steps completed", f"Output: {output_dir}", tone="success")


if __name__ == "__main__":
    main()
