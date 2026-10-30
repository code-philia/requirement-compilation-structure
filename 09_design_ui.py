"""Step 09: design all leaf requirements' UI/data without implementing pages."""

from contextlib import ExitStack
from pathlib import Path

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.stages.frontend.context import load_ui_context
from infrastructure.stages.frontend.ui.synthesis import synthesize_ui
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log


def design_frontend_ui(input_dir: Path, arc_dir: Path, pause: bool = False, top_k: int = 3,
        max_fixtures: int = 3) -> dict:
    if min(top_k, max_fixtures) < 1:
        raise ValueError("--top-k and --max-fixtures must be positive")
    tree, images, contexts = load_ui_context(arc_dir, input_dir)
    console, model = DemoConsole(pause), TextModel()
    design = synthesize_ui(arc_dir, tree, images, contexts,
        model, console, top_k, max_fixtures)
    print(f"UI/data design saved: {arc_dir / 'ui_design.json'}\nRun 10_implement_ui.py to generate existence tests and implement the pages.", flush=True)
    return design


def main() -> None:
    parser = create_parser("Step 09: UI/data Design with Page RAG")
    parser.add_argument("--top-k", type=int, default=3, help="Number of coarse page RAG candidates")
    parser.add_argument("--max-fixtures", type=int, default=3, help="Maximum named display states per page; compiler-owned default is free")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            design_frontend_ui(input_dir, output_dir / ".arc", args.pause, args.top_k, args.max_fixtures)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
