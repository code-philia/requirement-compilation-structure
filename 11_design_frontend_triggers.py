"""Step 11: Frontend trigger design."""

from contextlib import ExitStack
from pathlib import Path

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.stages.frontend.context import load_frontend_context, load_ui_design, behavior_contexts
from infrastructure.stages.frontend.triggers.synthesis import synthesize_triggers
from infrastructure.stages.frontend.triggers.design import empty_triggers
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.files import save_json


def design_frontend_triggers(input_dir: Path, arc_dir: Path, pause: bool = False, max_attempts: int = 3) -> dict:
    if max_attempts < 0:
        raise ValueError("--max-attempts must be nonnegative; use 0 for unlimited attempts")
    tree, _, backend, images, contexts = load_frontend_context(arc_dir, input_dir)
    ui = load_ui_design(arc_dir, tree)
    console = DemoConsole(pause)
    if not ui["pages"]:
        result = empty_triggers(tree)
        save_json(arc_dir / "frontend_triggers.json", result)
        console.show("Step 11 | No UI triggers", "Empty trigger design saved; no model calls were made.")
        return result
    result = synthesize_triggers(arc_dir, ui, tree, backend,
        behavior_contexts(contexts), TextModel(), console, max_attempts)
    console.show("Step 11 | Trigger design complete", f"Triggers: {len(result['triggers'])}\nSaved: {arc_dir / 'frontend_triggers.json'}\nApplication code and UI/data design were not changed. Step 12 implements triggers through E2E TDD.")
    return result


def main() -> None:
    parser = create_parser("Step 11: Frontend Trigger Design")
    parser.add_argument("--max-attempts", type=int, default=3,
        help="Maximum proposals per trigger design; 0 retries until valid (default: 3)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            design_frontend_triggers(input_dir, output_dir / ".arc", args.pause, args.max_attempts)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
