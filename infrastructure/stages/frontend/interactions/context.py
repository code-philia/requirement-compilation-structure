"""Load JSON artifacts and check DB obligations before interaction implementation."""

from infrastructure.utils.files import read_artifact
from infrastructure.stages.frontend.context import load_frontend_context, load_ui_design, behavior_contexts
from infrastructure.stages.frontend.interactions.contracts import validate_contract
from infrastructure.stages.frontend.interactions.design import validate_interactions


def load_e2e_context(arc_dir, input_dir):
    """Load UI/interaction artifacts with JSON and DB-field obligation checks."""
    tree, schema, obligations, backend, images, contexts = load_frontend_context(arc_dir, input_dir)
    ui = load_ui_design(arc_dir, tree, images)
    interactions = read_artifact(arc_dir, "ui_interactions.json")
    validate_interactions(interactions, ui, tree, schema, obligations, backend, tree.leaves, complete=True)
    for eid, contract in interactions["contracts"].items():
        validate_contract(eid, contract)
    return tree, schema, backend, ui, interactions, images, behavior_contexts(contexts)
