"""Step 11: Trigger/event Decomposition, Obligation Propagation, and Contract Inference."""

from contextlib import ExitStack
from pathlib import Path

from infrastructure.utils.files import read_artifact
from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.stages.frontend.context import load_frontend_context, load_ui_design
from infrastructure.stages.frontend.interactions.synthesis import synthesize_interactions
from infrastructure.stages.frontend.ui.testing import existence_suite, test_path
from infrastructure.stages.frontend.interactions.design import empty_interactions, validate_interactions
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.files import save_json


def design_ui_interactions(input_dir: Path, arc_dir: Path, pause: bool = False, top_k: int = 6) -> dict:
    if top_k < 1:
        raise ValueError("--top-k must be positive")
    tree, schema, obligations, backend, images, contexts = load_frontend_context(arc_dir, input_dir)
    ui = load_ui_design(arc_dir, tree, images)
    checks = read_artifact(arc_dir, "ui_checks.json")
    expected_status = "GREEN" if ui["pages"] else "NO_UI"
    if not isinstance(checks, dict) or checks.get("status") != expected_status:
        raise ValueError("Run 10_implement_ui.py successfully before designing interactions")
    pages = checks.get("pages", {})
    if not isinstance(pages, dict) or set(pages) != set(ui["pages"]) or any(
            not isinstance(page, dict) or page.get("status") != "GREEN" for page in pages.values()):
        raise ValueError("The step 10 report must cover every current UI page; rerun step 10")
    for pid in ui["pages"]:
        relative = test_path(pid)
        path = arc_dir.parent / relative
        if pages[pid].get("test_path") != relative or not path.is_file() or path.read_text(encoding="utf-8") != existence_suite(ui, pid):
            raise ValueError(f"Step 10 existence tests do not match the current UI/data design for {pid}; rerun step 10")
    console = DemoConsole(pause)
    if not ui["pages"]:
        result = empty_interactions(tree)
        validate_interactions(result, ui, tree, schema, obligations, backend, tree.leaves, complete=True)
        save_json(arc_dir / "ui_interactions.json", result)
        console.show("Step 11 | No UI interactions", "Empty interaction design saved; no model calls were made.")
        return result
    result = synthesize_interactions(arc_dir, ui, tree, schema, obligations, backend,
        contexts, TextModel(), console, top_k)
    console.show("Step 11 | Interaction design complete", f"Triggers: {len(result['triggers'])}\nEvents/contracts: {len(result['events'])}\nSaved: {arc_dir / 'ui_interactions.json'}\nApplication code and UI/data design were not changed. Step 12 implements interactions through E2E TDD.")
    return result


def main() -> None:
    parser = create_parser("Step 11: UI Interaction Design and Contract Inference")
    parser.add_argument("--top-k", type=int, default=6, help="Number of coarse event/API RAG matches")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir))
            design_ui_interactions(input_dir, output_dir / ".arc", args.pause, args.top_k)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
