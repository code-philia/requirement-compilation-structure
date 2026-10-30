"""Step 12: implement frontend triggers through real-application Playwright E2E TDD."""

from contextlib import ExitStack
from pathlib import Path

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.stages.frontend.triggers.context import load_e2e_context
from infrastructure.stages.frontend.triggers.implementation import run_trigger_tdd
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.files import save_json


def implement_frontend_triggers(input_dir: Path, arc_dir: Path, pause: bool = False,
        max_turns: int = 5, max_tests: int = 5) -> dict:
    if min(max_turns, max_tests) < 1:
        raise ValueError("--max-turns and --max-tests must be positive")
    tree, schema, backend, ui, interactions, images, contexts = load_e2e_context(arc_dir, input_dir)
    report = {"status": "PREPARING", "requirements": {rid: {"status": "NO_DIRECT_TRIGGERS", "triggers": []}
        for rid in tree.requirements if tree.children[rid]}}
    save_json(arc_dir / "frontend_e2e.json", report)
    try:
        if not ui["pages"]:
            report.update({"status": "NO_UI", "summary": {"requirements": 0, "triggers": 0, "e2e_tests": 0, "ui_tests": 0, "failed": 0}})
            save_json(arc_dir / "frontend_e2e.json", report)
            return report
        model = TextModel() if any(interactions["requirements"][rid] or tree.own_steps[rid] for rid in tree.leaves) else None
        result = run_trigger_tdd(arc_dir, tree, schema, backend, ui, interactions, images,
            contexts, model, DemoConsole(pause), report, max_turns, max_tests)
        print(f"Frontend E2E TDD GREEN: {result['summary']}\nReport: {arc_dir / 'frontend_e2e.json'}", flush=True)
        return result
    except BaseException as error:
        report.update({"status": "FAILED", "error": str(error)})
        for requirement in report["requirements"].values():
            if requirement["status"] not in {"GREEN", "NO_TRIGGERS", "NO_DIRECT_TRIGGERS"}:
                requirement["status"] = "FAILED"
        save_json(arc_dir / "frontend_e2e.json", report)
        raise


def main() -> None:
    parser = create_parser("Step 12: Frontend Trigger Implementation through Playwright E2E TDD")
    parser.add_argument("--max-turns", type=int, default=5, help="Maximum edit rounds per requirement's test/implementation agent")
    parser.add_argument("--max-tests", type=int, default=5, help="Maximum key E2E cases per requirement")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            implement_frontend_triggers(input_dir, output_dir / ".arc", args.pause, args.max_turns, args.max_tests)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
