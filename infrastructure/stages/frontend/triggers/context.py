"""Load UI, API and trigger artifacts for executable acceptance."""

from infrastructure.utils.files import read_artifact
from infrastructure.stages.frontend.context import load_frontend_context, load_ui_design, behavior_contexts


def load_e2e_context(arc_dir, input_dir):
    tree, schema, backend, images, contexts = load_frontend_context(arc_dir, input_dir)
    ui = load_ui_design(arc_dir, tree)
    triggers = read_artifact(arc_dir, "frontend_triggers.json")
    return tree, schema, backend, ui, triggers, images, behavior_contexts(contexts)
