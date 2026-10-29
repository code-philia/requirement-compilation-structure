"""Step 11: Trigger/event Decomposition, Obligation Propagation, and Contract Inference."""

from contextlib import ExitStack
from pathlib import Path

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.stages.frontend.context import load_frontend_context, load_ui_design, behavior_contexts
from infrastructure.stages.frontend.interactions.synthesis import synthesize_interactions
from infrastructure.stages.frontend.interactions.design import empty_interactions, validate_interactions
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.files import save_json


def design_ui_interactions(input_dir: Path, arc_dir: Path, pause: bool = False, max_attempts: int = 3) -> dict:
    if max_attempts < 0:
        raise ValueError("--max-attempts must be nonnegative; use 0 for unlimited attempts")
    tree, schema, obligations, backend, images, contexts = load_frontend_context(arc_dir, input_dir)
    ui = load_ui_design(arc_dir, tree, images)
    console = DemoConsole(pause)
    if not ui["pages"]:
        result = empty_interactions(tree)
        validate_interactions(result, ui, tree, schema, obligations, backend, tree.leaves, complete=True)
        save_json(arc_dir / "ui_interactions.json", result)
        console.show("Step 11 | No UI interactions", "Empty interaction design saved; no model calls were made.")
        return result
    result = synthesize_interactions(arc_dir, ui, tree, schema, obligations, backend,
        behavior_contexts(contexts), TextModel(), console, max_attempts)
    console.show("Step 11 | Interaction design complete", f"Triggers: {len(result['triggers'])}\nEvents/contracts: {len(result['events'])}\nSaved: {arc_dir / 'ui_interactions.json'}\nApplication code and UI/data design were not changed. Step 12 implements interactions through E2E TDD.")
    return result


def main() -> None:
    parser = create_parser("Step 11: UI Interaction Design and Contract Inference")
    parser.add_argument("--max-attempts", type=int, default=3,
        help="Maximum proposals per decomposition or event contract; 0 retries until valid (default: 3)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir))
            design_ui_interactions(input_dir, output_dir / ".arc", args.pause, args.max_attempts)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
