"""Trigger/event references and frontend/database obligation conservation."""

from copy import deepcopy

from infrastructure.stages.frontend.ui.design import page_context, page_elements
from infrastructure.stages.database.obligations.rules import difference, union
from infrastructure.shared.models.structure import object_fields, string_list

class InteractionCoverageError(ValueError):
    """A rejected interaction decomposition with structured gaps for model correction."""
    def __init__(self, identity, required, combined, gaps):
        """Store expected obligations, the proposed union, and missing fields for bounded correction feedback."""
        self.feedback = {"identity": identity, "required": required, "actual_union": combined, **gaps}
        super().__init__(f"Interaction Obligation Propagation failed: {self.feedback}")


def empty_interactions(tree):
    """Create empty trigger/event registries and requirement/step ownership records for the requirement tree."""
    return {"triggers": {}, "events": {}, "contracts": {},
        "requirements": {rid: [] for rid in tree.requirements}, "steps": {sid: [] for sid in tree.steps}}


def require_fields(value, fields, label):
    object_fields(value, {field: object for field in fields}, label)


def text(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a JSON string")


def relevant_pages(ui, rid):
    """Return the UI page contexts directly used by the selected requirement."""
    selected = set(ui["requirements"][rid])
    return {pid: page_context(ui, pid) for pid in ui["pages"] if selected.intersection(page_elements(ui, pid))}


def event_ids(result, tids):
    """Collect unique event IDs referenced by the selected triggers."""
    return {result["triggers"][tid]["action"] for tid in tids}


def api_ids(event):
    """Collect canonical backend API IDs called by one event's actions."""
    return {action["api"] for action in event["actions"] if action["kind"] == "api"}


def event_obligations(event, backend):
    """Derive an event's database effects from the APIs in its ordered actions."""
    called = api_ids(event)
    unknown = called - set(backend["apis"])
    if unknown:
        raise ValueError(f"Unknown backend APIs in event actions: {sorted(unknown)}")
    return union(backend["apis"][aid] for aid in called)


def check_coverage(label, required, actual, allowed=None):
    """Compare required and combined read/write sets, rejecting missing fields and any disallowed extra symbols."""
    gaps = {"missing": difference(required, actual)}
    if allowed is not None:
        gaps["excess"] = difference(actual, allowed)
    if any(fields for gap in gaps.values() for fields in gap.values()):
        raise InteractionCoverageError(label, required, actual, gaps)


def validate_interactions(result, ui, tree, schema, obligations, backend, analyzed, complete=False):
    """Check JSON shape and DB-field coverage of frontend calls; no UI or P/Q policy."""
    object_fields(result, {key: dict for key in ("triggers", "events", "contracts", "requirements", "steps")}, "interactions")
    for eid, event in result["events"].items():
        object_fields(event, {"description": str, "write": list, "actions": list}, eid)
        string_list(event["write"], f"{eid}.write")
        for action in event["actions"]:
            object_fields(action, {"id": str, "kind": str, "description": str}, f"{eid}.action")
            if action["kind"] == "api":
                object_fields(action, {"api": str}, "API action")
                if action["api"] not in backend["apis"]:
                    raise ValueError(f"Unknown API in DB obligation chain: {action['api']}")
            elif action["kind"] == "navigate":
                object_fields(action, {"page": str}, "navigation action")
    for tid, trigger in result["triggers"].items():
        object_fields(trigger, {"source": str, "event": str, "action": str}, tid)
    for kind, expected in (("requirements", tree.requirements), ("steps", tree.steps)):
        for identity in expected:
            result[kind].setdefault(identity, [])
        for identity, tids in result[kind].items():
            string_list(tids, f"{kind}.{identity}")
    checked = tree.leaves if complete else analyzed
    for rid in checked:
        tids = result["requirements"].get(rid, [])
        if not tids and not relevant_pages(ui, rid):
            continue
        unknown = set(tids) - set(result["triggers"])
        if unknown:
            raise ValueError(f"Unknown triggers in DB obligation chain: {sorted(unknown)}")
        eids = event_ids(result, tids)
        unknown = eids - set(result["events"])
        if unknown:
            raise ValueError(f"Unknown events in DB obligation chain: {sorted(unknown)}")
        actual = union(event_obligations(result["events"][eid], backend) for eid in eids)
        check_coverage(rid, obligations["requirements"][rid], actual, obligations["requirements"][rid])


def apply_decomposition(current, proposal, rid, ui, tree, schema, obligations, backend, analyzed):
    object_fields(proposal, {"triggers": dict, "events": dict, "requirement_triggers": list, "step_triggers": dict}, "interaction proposal")
    updated = deepcopy(current)
    for kind in ("triggers", "events"):
        updated[kind].update(deepcopy(proposal[kind]))
    updated["requirements"][rid] = string_list(proposal["requirement_triggers"], "requirement_triggers")
    updated["steps"].update(deepcopy(proposal["step_triggers"]))
    validate_interactions(updated, ui, tree, schema, obligations, backend, [*analyzed, rid])
    return updated
