"""Validate immutable design inputs before interaction implementation starts."""

from infrastructure.utils.files import read_artifact
from infrastructure.stages.backend.runtime import api_entrypoint
from infrastructure.stages.frontend.context import load_frontend_context, load_ui_design, behavior_contexts
from infrastructure.stages.frontend.interactions.contracts import validate_contract
from infrastructure.stages.frontend.ui.testing import validate_ui_baseline
from infrastructure.stages.frontend.interactions.design import validate_interactions
from infrastructure.shared.project.entrypoints import implementation_entrypoint


def load_e2e_context(arc_dir, input_dir):
    """Validate step 08/10/11 artifacts, frozen UI tests, and fixed API/page implementations before interaction TDD."""
    tree, schema, obligations, backend, images, contexts = load_frontend_context(arc_dir, input_dir)
    ui = load_ui_design(arc_dir, tree, images)
    interactions = read_artifact(arc_dir, "ui_interactions.json")
    validate_interactions(interactions, ui, tree, schema, obligations, backend, tree.leaves, complete=True)
    if set(interactions["contracts"]) != set(interactions["events"]):
        raise ValueError("Run step 11: every event needs exactly one contract")
    for eid, contract in interactions["contracts"].items():
        validate_contract(eid, contract)
    validate_ui_baseline(arc_dir, ui)
    output = arc_dir.parent.resolve()
    for pid in ui["pages"]:
        if not implementation_entrypoint(output, "page", pid):
            raise ValueError(f"Missing page implementation: {pid}")
    backend_checks = read_artifact(arc_dir, "backend_tdd.json")
    if not isinstance(backend_checks, dict) or backend_checks.get("status") != ("GREEN" if backend["apis"] else "NO_APIS"):
        raise ValueError("Complete backend step 08 successfully before E2E implementation")
    for aid in backend["apis"]:
        if api_entrypoint(output, aid) is None:
            raise ValueError(f"Missing backend implementation: {aid}; rerun step 08")
    return tree, schema, backend, ui, interactions, images, behavior_contexts(contexts)
