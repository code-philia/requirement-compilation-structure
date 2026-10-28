"""Trigger/event references and frontend/database obligation conservation."""

from copy import deepcopy
import re

from infrastructure.stages.frontend.ui.design import page_context, page_elements
from infrastructure.stages.database.obligations.records import validate_record, field_symbols
from infrastructure.stages.database.obligations.rules import difference, union

IDENTITY = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")
INTERACTIONS = {"click", "change", "input", "submit", "keydown", "keyup", "mount"}


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
    """Require an object with exactly the declared fields and report the labeled validation boundary."""
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f"{label} must contain exactly {sorted(fields)}")


def identifiers(value, allowed, label):
    """Validate a unique ID list against the allowed registry and return its set of IDs."""
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be an array of identifiers")
    if len(value) != len(set(value)) or set(value) - set(allowed):
        raise ValueError(f"Duplicate or unknown identifiers in {label}: {value}")
    return set(value)


def text(value, label, optional=False):
    """Reject missing or empty descriptive text unless an optional value is absent."""
    if optional and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")


def data_types(ui):
    """Index frontend data variable names and types from the UI element descriptors."""
    return {data["var"]: data["dtype"] for node in ui["elements"].values() for data in node.get("data", [])}


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


def check_coverage(label, required, actual, allowed=None):
    """Compare required and combined read/write sets, rejecting missing fields and any disallowed extra symbols."""
    gaps = {"missing": difference(required, actual)}
    if allowed is not None:
        gaps["excess"] = difference(actual, allowed)
    if any(fields for gap in gaps.values() for fields in gap.values()):
        raise InteractionCoverageError(label, required, actual, gaps)


def validate_interactions(result, ui, tree, schema, obligations, backend, analyzed, complete=False):
    """Validate trigger/event ownership, UI sources, frontend/DB effects, backend calls, and obligation-union coverage."""
    require_fields(result, {"triggers", "events", "contracts", "requirements", "steps"}, "Interaction design")
    if any(not isinstance(value, dict) for value in result.values()):
        raise ValueError("Interaction registries must be objects")
    if set(result["requirements"]) != set(tree.requirements) or set(result["steps"]) != set(tree.steps):
        raise ValueError("Interaction bindings must retain every requirement/step ID")
    variables, symbols = set(ui["bindings"]), field_symbols(schema)
    for eid, event in result["events"].items():
        if not IDENTITY.fullmatch(eid):
            raise ValueError(f"Invalid event ID: {eid}")
        require_fields(event, {"description", "read", "write", "obligations", "actions"}, eid)
        text(event["description"], eid)
        identifiers(event["read"], variables, eid + ".read")
        identifiers(event["write"], variables, eid + ".write")
        validate_record(event["obligations"], symbols, eid)
        if not isinstance(event["actions"], list) or not event["actions"]:
            raise ValueError(f"Provide ordered actions for {eid}")
        action_ids = set()
        for action in event["actions"]:
            if not isinstance(action, dict) or not isinstance(action.get("kind"), str) or action["kind"] not in {"local", "api", "navigate"}:
                raise ValueError(f"Invalid action kind in {eid}")
            kind = action["kind"]
            require_fields(action, {"id", "kind", "description", "when", "read", "write"} |
                ({"api"} if kind == "api" else {"page"} if kind == "navigate" else set()), eid + " action")
            aid = action["id"]
            if not isinstance(aid, str) or not IDENTITY.fullmatch(aid) or aid in action_ids:
                raise ValueError(f"Action IDs must be unique within {eid}")
            action_ids.add(aid)
            text(action["description"], aid)
            text(action["when"], aid + ".when", optional=True)
            identifiers(action["read"], variables, aid + ".read")
            identifiers(action["write"], variables, aid + ".write")
            if kind == "api" and (not isinstance(action["api"], str) or action["api"] not in backend["apis"]):
                raise ValueError(f"Unknown backend API: {aid}")
            if kind == "navigate" and (not isinstance(action["page"], str) or action["page"] not in ui["pages"]):
                raise ValueError(f"Unknown navigation page: {aid}")
            if kind != "local" and action["write"]:
                raise ValueError(f"Frontend state updates need explicit local actions after API results: {aid}")
        effects = union(event["actions"])
        check_coverage(eid + " frontend effects", {key: event[key] for key in ("read", "write")}, effects,
            {key: event[key] for key in ("read", "write")})
        called = union(backend["apis"][aid] for aid in api_ids(event))
        check_coverage(eid + " DB effects", event["obligations"], called, event["obligations"])
    emissions = {}
    for tid, trigger in result["triggers"].items():
        if not IDENTITY.fullmatch(tid):
            raise ValueError(f"Invalid trigger ID: {tid}")
        require_fields(trigger, {"source", "event", "guard", "read", "action", "write"}, tid)
        if not isinstance(trigger["source"], str) or trigger["source"] not in ui["elements"]:
            raise ValueError(f"Unknown trigger UI source: {tid}")
        if not isinstance(trigger["event"], str) or trigger["event"] not in INTERACTIONS:
            raise ValueError(f"Unsupported trigger interaction: {tid}")
        if trigger["event"] == "mount" and trigger["source"] not in {page["root"] for page in ui["pages"].values()}:
            raise ValueError(f"Page-entry triggers must use a canonical page root: {tid}")
        source_type = ui["elements"][trigger["source"]].get("type", "container")
        if trigger["event"] == "submit" and source_type != "form":
            raise ValueError(f"A native submit trigger must use a form; buttons use click: {tid}")
        if not isinstance(trigger["action"], str) or trigger["action"] not in result["events"]:
            raise ValueError(f"Unknown trigger event handler: {tid}")
        text(trigger["guard"], tid + ".guard", optional=True)
        reads = identifiers(trigger["read"], variables, tid + ".read")
        writes = identifiers(trigger["write"], variables, tid + ".write")
        event = result["events"][trigger["action"]]
        if not set(event["read"]).issubset(reads) or writes != set(event["write"]):
            raise ValueError(f"Trigger must cover its event reads and exactly summarize its writes: {tid}")
        emission = (trigger["source"], trigger["event"])
        if emission in emissions:
            raise ValueError(f"Reuse one trigger per source/interaction; combine branches in its event: {tid}/{emissions[emission]}")
        emissions[emission] = tid
    for kind, allowed in (("requirements", tree.requirements), ("steps", tree.steps)):
        for identity, tids in result[kind].items():
            identifiers(tids, result["triggers"], kind + ":" + identity)
    used = {tid for tids in result["requirements"].values() for tid in tids}
    if used != set(result["triggers"]) or {tr["action"] for tr in result["triggers"].values()} != set(result["events"]):
        raise ValueError("Unbound triggers and event handlers are not allowed")
    for rid in tree.requirements:
        if tree.children[rid]:
            if result["requirements"][rid] or any(result["steps"][sid] for sid in tree.own_steps[rid]):
                raise ValueError("Organizational parents must not inherit child triggers/events")
            continue
        if rid not in analyzed:
            if result["requirements"][rid] or any(result["steps"][sid] for sid in tree.own_steps[rid]):
                raise ValueError(f"Only the current/previously analyzed leaves may have bindings: {rid}")
            continue
        tids = result["requirements"][rid]
        events = [result["events"][eid] for eid in event_ids(result, tids)]
        available = relevant_pages(ui, rid)
        sources = {uid for page in available.values() for uid in page["elements"]}
        allowed_vars = {var for page in available.values() for var in page["bindings"]}
        called = set()
        for tid in tids:
            trigger = result["triggers"][tid]
            if trigger["source"] not in sources or (set(trigger["read"]) | set(trigger["write"])) - allowed_vars:
                raise ValueError(f"Retrieve and use the requirement's page subtrees and data: {rid}/{tid}")
            called.update(api_ids(result["events"][trigger["action"]]))
        if called - set(backend["requirements"][rid]):
            raise ValueError(f"Use only directly allocated backend APIs for {rid}; other page lifecycle behavior remains owned by its original requirement")
        if set(backend["requirements"][rid]) - called:
            raise ValueError(f"Every directly allocated API needs an event call, including APIs with empty DB effects: {rid}")
        actual = union(event["obligations"] for event in events)
        check_coverage(rid, obligations["requirements"][rid], actual, obligations["requirements"][rid])
        for sid in tree.own_steps[rid]:
            step_tids = result["steps"][sid]
            if not set(step_tids).issubset(tids):
                raise ValueError(f"Step triggers must be directly assigned to their requirement: {sid}")
            check_coverage(sid, obligations["steps"][sid], union(result["events"][eid]["obligations"] for eid in event_ids(result, step_tids)))
            # A rejection step may call an API that writes on success. Its lack
            # of writes is a branch contract, not a reason to forbid that call.
            if ui["steps"][sid] and not step_tids:
                raise ValueError(f"Provide interaction traceability for the UI step: {sid}")
        # Check current-leaf editable bindings inside the bounded proposal loop,
        # so missing input wiring is returned to the model rather than discovered
        # only after every leaf has already completed decomposition.
        for uid in ui["requirements"][rid]:
            node = ui["elements"][uid]
            if "user_write" in node.get("mode", []) and node.get("data"):
                changes = [result["triggers"][tid] for tid in tids if result["triggers"][tid]["source"] == uid
                    and result["triggers"][tid]["event"] in {"change", "input"}]
                if not changes or not {item["var"] for item in node["data"]}.issubset({var for tr in changes for var in tr["write"]}):
                    raise ValueError(f"Editable UI data needs a directly associated input/change trigger: {uid}")
    if complete:
        for rid in tree.postorder:
            if tree.children[rid]:
                check_coverage(rid + " subtree", obligations["requirements"][rid], union(obligations["requirements"][child] for child in tree.children[rid]))
        if set(analyzed) != set(tree.leaves):
            raise ValueError("All leaves must complete interaction design")


def apply_decomposition(current, proposal, rid, retrieved, ui, tree, schema, obligations, backend, analyzed):
    """Merge a requirement's trigger/event proposal into a copy, enforce retrieved reuse, and validate before accepting it."""
    require_fields(proposal, {"triggers", "events", "requirement_triggers", "step_triggers", "explanation"}, "Interaction proposal")
    text(proposal["explanation"], "explanation")
    updated = deepcopy(current)
    for kind in ("triggers", "events"):
        if not isinstance(proposal[kind], dict):
            raise ValueError(f"{kind} must be an object")
        if (set(proposal[kind]) & set(current[kind])) - set(retrieved[kind]):
            raise ValueError(f"Retrieve existing {kind} before changing them")
        updated[kind].update(deepcopy(proposal[kind]))
    if not isinstance(proposal["step_triggers"], dict) or set(proposal["step_triggers"]) != set(tree.own_steps[rid]):
        raise ValueError("Return exactly the current leaf's own step IDs")
    updated["requirements"][rid] = deepcopy(proposal["requirement_triggers"])
    updated["steps"].update(deepcopy(proposal["step_triggers"]))
    validate_interactions(updated, ui, tree, schema, obligations, backend, [*analyzed, rid])
    return updated
