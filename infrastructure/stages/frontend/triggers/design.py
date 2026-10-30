"""Frontend triggers and database effects derived from their API actions."""

from copy import deepcopy

from infrastructure.stages.frontend.ui.design import page_context, page_elements
from infrastructure.stages.database.obligations.rules import union


def empty_triggers(tree):
    return {"triggers": {}, "requirements": {rid: [] for rid in tree.requirements},
        "steps": {sid: [] for sid in tree.steps}}


def relevant_pages(ui, rid):
    selected = set(ui["requirements"].get(rid, []))
    return {pid: page_context(ui, pid) for pid in ui["pages"] if selected.intersection(page_elements(ui, pid))}


def api_ids(trigger):
    return {action["api"] for action in trigger["action"] if action["kind"] == "api"}


def trigger_obligations(trigger, backend):
    """Compute DB R/W for implementation context, without frontend coverage gates."""
    return union(backend["apis"][aid] for aid in api_ids(trigger))


def apply_decomposition(current, proposal, rid):
    updated = deepcopy(current)
    updated["triggers"].update(deepcopy(proposal["triggers"]))
    updated["requirements"][rid] = proposal["requirement_triggers"]
    updated["steps"].update(deepcopy(proposal.get("step_triggers", {})))
    return updated
