"""Load UI, API and trigger artifacts for executable acceptance."""

from infrastructure.utils.files import read_artifact
from infrastructure.stages.frontend.context import load_frontend_context, load_ui_design
from infrastructure.stages.frontend.triggers.acceptance import original_requirements
from infrastructure.stages.backend.context import requirement_context


def load_e2e_context(arc_dir, input_dir):
    visual_tree, schema, backend, images, visual_contexts = load_frontend_context(arc_dir, input_dir)
    tree = original_requirements(input_dir)
    tree.backend_evidence = getattr(visual_tree,"backend_evidence",{})
    tree.backend_foundation = getattr(visual_tree,"backend_foundation",{"enabled":False})
    contexts = {rid: {**requirement_context(tree, rid), "platform_http": visual_contexts[rid].get("platform_http",{})} for rid in tree.leaves}
    ui = load_ui_design(arc_dir, tree)
    triggers = read_artifact(arc_dir, "frontend_triggers.json")
    return tree, schema, backend, ui, triggers, images, contexts
