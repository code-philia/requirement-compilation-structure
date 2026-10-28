"""Validate immutable design inputs before interaction implementation starts."""

from infrastructure.utils.files import read_artifact
from infrastructure.stages.backend.runtime import api_entrypoint
from infrastructure.stages.frontend.context import load_frontend_context, load_ui_design
from infrastructure.stages.frontend.interactions.contracts import validate_contract
from infrastructure.stages.frontend.ui.testing import existence_suite, test_path
from infrastructure.stages.frontend.interactions.design import validate_interactions
from infrastructure.shared.agent.traceability import FileIndex
from infrastructure.shared.project.entrypoints import resolve_entrypoint
from infrastructure.stages.frontend.interactions.runtime import PROTECTED


def load_e2e_context(arc_dir, input_dir):
    """Validate step 08/10/11 artifacts, frozen UI tests, and recorded API/page entrypoints before interaction TDD."""
    tree, schema, obligations, backend, images, contexts = load_frontend_context(arc_dir, input_dir)
    ui = load_ui_design(arc_dir, tree, images)
    interactions = read_artifact(arc_dir, "ui_interactions.json")
    validate_interactions(interactions, ui, tree, schema, obligations, backend, tree.leaves, complete=True)
    if set(interactions["contracts"]) != set(interactions["events"]):
        raise ValueError("Run step 11: every event needs exactly one contract")
    for eid, contract in interactions["contracts"].items():
        validate_contract(eid, contract, interactions, ui, backend)
    checks = read_artifact(arc_dir, "ui_checks.json")
    if not isinstance(checks, dict) or checks.get("status") != ("GREEN" if ui["pages"] else "NO_UI") or not isinstance(checks.get("pages"), dict) or set(checks["pages"]) != set(ui["pages"]):
        raise ValueError("Complete step 10 successfully before step 12")
    output, index = arc_dir.parent.resolve(), FileIndex(arc_dir.parent)
    for pid in ui["pages"]:
        relative = test_path(pid)
        if not isinstance(checks["pages"][pid], dict) or checks["pages"][pid].get("status") != "GREEN" or not (output / relative).is_file() or (output / relative).read_text() != existence_suite(ui, pid):
            raise ValueError(f"UI design/existence tests changed for {pid}; rerun steps 10 and 11")
        if not resolve_entrypoint(output, index, f"frontend:page:{pid}", "frontend/src", (".ts", ".tsx"), PROTECTED):
            raise ValueError(f"Missing page implementation: {pid}")
    backend_checks = read_artifact(arc_dir, "backend_tdd.json")
    if not isinstance(backend_checks, dict) or backend_checks.get("status") != ("GREEN" if backend["apis"] else "NO_APIS"):
        raise ValueError("Complete backend step 08 successfully before E2E implementation")
    for aid in backend["apis"]:
        if api_entrypoint(output, index, aid) is None:
            raise ValueError(f"Missing backend implementation: {aid}; rerun step 08")
    return tree, schema, backend, ui, interactions, images, contexts, index
