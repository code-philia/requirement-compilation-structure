"""Load UI, API and trigger artifacts for executable acceptance."""

from infrastructure.utils.files import read_artifact
from infrastructure.stages.frontend.context import load_frontend_context, load_ui_design
from infrastructure.stages.frontend.triggers.acceptance import original_requirements
from infrastructure.stages.backend.context import requirement_context


def load_e2e_context(arc_dir, input_dir):
    _, schema, backend, images, _ = load_frontend_context(arc_dir, input_dir)
    tree = original_requirements(input_dir)
    contexts = {rid: requirement_context(tree, rid) for rid in tree.leaves}
    ui = load_ui_design(arc_dir, tree)
    triggers = read_artifact(arc_dir, "frontend_triggers.json")
    return tree, schema, backend, ui, triggers, images, contexts
