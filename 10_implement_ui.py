"""Step 10: implement the saved UI/data design through UI existence TDD."""

from contextlib import ExitStack
from pathlib import Path

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.stages.frontend.context import load_frontend_context, load_ui_design
from infrastructure.stages.frontend.ui.implementation import implement_ui
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.files import save_json


def implement_frontend_ui(input_dir: Path, arc_dir: Path, pause: bool = False,
        max_turns: int = 18) -> dict:
    if max_turns < 1:
        raise ValueError("--max-turns must be positive")
    if not (arc_dir / "ui_design.json").is_file():
        raise ValueError("Run 09_design_ui.py first to create .arc/ui_design.json")
    report = {"status": "VALIDATING", "pages": {}}
    save_json(arc_dir / "ui_checks.json", report)
    try:
        tree, _, _, _, images, contexts = load_frontend_context(arc_dir, input_dir)
        design = load_ui_design(arc_dir, tree, images)
        console = DemoConsole(pause)
        console.show("Step 10 | Saved UI/data design", f"Loaded {arc_dir / 'ui_design.json'}\nPages: {', '.join(design['pages']) or '(none)'}\nGenerate existence tests and implement this design without rerunning synthesis.")
        if not design["pages"]:
            report["status"] = "NO_UI"
            save_json(arc_dir / "ui_checks.json", report)
            print("No pages require implementation; no model calls, dependency installation or browser tests were run.", flush=True)
            return report
        result = implement_ui(arc_dir, design, TextModel(), console, report, max_turns,
            images=images, requirement_contexts=contexts)
        print(f"UI existence TDD GREEN. Checks: {arc_dir / 'ui_checks.json'}", flush=True)
        return result
    except BaseException as error:
        report.update({"status": "FAILED", "error": str(error)})
        for page in report["pages"].values():
            if page["status"] != "GREEN":
                page["status"] = "FAILED"
        save_json(arc_dir / "ui_checks.json", report)
        raise


def main() -> None:
    parser = create_parser("Step 10: Playwright UI Existence Tests and UI Implementation TDD")
    parser.add_argument("--max-turns", type=int, default=18, help="Maximum edit/check turns per page implementation")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir))
            implement_frontend_ui(input_dir, output_dir / ".arc", args.pause, args.max_turns)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
