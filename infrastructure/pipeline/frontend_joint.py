"""Outline pages, then implement native UI/interactions directly from source evidence."""

from infrastructure.stages.frontend.context import load_frontend_context
from infrastructure.shared.agent.outlines import plan_requirements, load_outline
from infrastructure.utils.files import save_json, read_artifact


def design_frontend_joint(input_dir, arc_dir, pause=False, max_attempts=5):
    tree, schema, backend, images, contexts = load_frontend_context(arc_dir, input_dir)
    # UI evidence/visual analysis remains in the context, but there is no component or trigger IR.
    return plan_requirements(arc_dir, 'frontend', tree, contexts, pause=pause, max_attempts=max_attempts)


def implement_frontend_joint(input_dir, arc_dir, pause=False):
    from infrastructure.stages.frontend.triggers.implementation import run_trigger_tdd
    from infrastructure.stages.frontend.triggers.acceptance import original_requirements
    from infrastructure.shared.models.text import TextModel
    from infrastructure.utils.presentation.console import DemoConsole
    visual_tree, schema, backend, images, contexts = load_frontend_context(arc_dir, input_dir)
    plan = load_outline(arc_dir, 'frontend')
    tree = original_requirements(input_dir)
    # Minimal adapter for the existing real-browser runner. No generated element tree,
    # presentation fixtures or trigger DSL; tests derive behavior from original scenarios.
    ui = {"outline": True, "pages": plan["items"], "elements": {},
        "requirements": plan["requirements"], "notes": plan["notes"]}
    interactions = {"triggers": {}, "requirements": {rid: [] for rid in tree.leaves}}
    previous = read_artifact(arc_dir, "frontend_e2e.json") if (arc_dir / "frontend_e2e.json").is_file() else {}
    report = {"previous_failures": {rid: {key: entry[key] for key in ("error", "feedback", "archive") if key in entry}
        for rid, entry in previous.get("requirements", {}).items() if entry.get("status") == "FAILED"},
        "status": "PREPARING", "requirements": {rid: {"status": "PENDING"} for rid in tree.leaves}}
    save_json(arc_dir / 'frontend_e2e.json', report)
    try:
        return run_trigger_tdd(arc_dir, tree, schema, backend, ui, interactions, images,
            contexts, TextModel(), DemoConsole(pause), report, joint_ui=True)
    except BaseException as error:
        report.update(status='FAILED', error=str(error))
        save_json(arc_dir / 'frontend_e2e.json', report)
        raise
