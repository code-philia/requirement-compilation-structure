"""Step 09: design all leaf requirements' UI/data without implementing pages."""

from pathlib import Path

from infrastructure.stages.frontend.context import load_frontend_context
from infrastructure.stages.frontend.ui.synthesis import synthesize_ui
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole


def design_frontend_ui(input_dir: Path, arc_dir: Path, pause: bool = False, top_k: int = 3,
        max_fixtures: int = 3) -> dict:
    if min(top_k, max_fixtures) < 1:
        raise ValueError("--top-k and --max-fixtures must be positive")
    tree, schema, _, contracts, images, contexts = load_frontend_context(arc_dir, input_dir)
    console, model = DemoConsole(pause), TextModel()
    design = synthesize_ui(arc_dir, tree, schema, contracts, images, contexts,
        model, console, top_k, max_fixtures)
    print(f"UI/data design saved: {arc_dir / 'ui_design.json'}\nRun 10_implement_ui.py to generate existence tests and implement the pages.", flush=True)
    return design
