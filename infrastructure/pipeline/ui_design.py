"""Step 07: design all leaf requirements' UI/data without implementing pages."""

from pathlib import Path

from infrastructure.stages.frontend.context import load_ui_context
from infrastructure.stages.frontend.ui.synthesis import synthesize_ui
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole


def design_frontend_ui(input_dir: Path, arc_dir: Path, pause: bool = False, top_k: int = 3,
        max_attempts: int = 10) -> dict:
    if top_k < 1:
        raise ValueError("--top-k must be positive")
    tree, images, contexts = load_ui_context(arc_dir, input_dir)
    console, model = DemoConsole(pause), TextModel(json_mode=False)
    design = synthesize_ui(arc_dir, tree, images, contexts,
        model, console, top_k, max_attempts)
    print(f"UI/data design saved: {arc_dir / 'ui_design.json'}\nRun main.py --stage 08 to generate existence tests and implement the pages.", flush=True)
    return design
