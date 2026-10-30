"""Canonical UI/data records and incremental design updates."""

from copy import deepcopy



INSTRUCTIONS = """Design UI and frontend data for the current leaf requirement.
Use requirement scenarios, supplied reference images and existing page subtrees.
Return {pages:{}, elements:{}, bindings:{}, requirement_ui:[], step_ui:{}}.
Return complete new or changed records keyed by ID; existing records may be reused
by reference. Updates replace records. Keep existing behavior when sharing a page.

Pages contain name, route, root (UI ID), images (image IDs), fixtures.
Fixtures describe display states: default={} plus useful variable overrides.
Elements contain type, parent (UI ID or null), mode, data, prop.
A page root is a UI element of type page. Other types describe ordinary HTML/UI
controls. mode is a list of user_read/user_write; data lists frontend variable names.
prop contains static labels/text/options/layout/style and optional visible conditions.

Bindings define frontend variables once, keyed by variable name, with dtype,
constraints (descriptions), initial and source (origin description).
Include input values, results, selections, loading and error state as needed.
Native editable values are synchronized by the UI host. Business behavior belongs
to triggers, designed later. UI does not declare database obligations or DB mappings.
Use data bindings to display API results later, without inventing production data.

requirement_ui lists the UI elements used by this requirement; step_ui associates
scenario steps with UI IDs. Non-UI requirements may return empty records and lists.
Images provide visual evidence; use image.page hints when supplied.
Do not return triggers, handlers, code or tests in this design response.
"""


def empty_design() -> dict:
    """Keep UI/data and requirement associations in five independent registries."""
    return {"pages": {}, "elements": {}, "bindings": {}, "requirements": {}, "steps": {}}


def page_elements(design: dict, pid: str) -> dict:
    """Return the IDs in one page's UI subtree, including its root."""
    root = design["pages"][pid]["root"]
    selected = {root}
    while True:
        expanded = selected | {uid for uid, node in design["elements"].items() if node.get("parent") in selected}
        if expanded == selected:
            return {uid: deepcopy(node) for uid, node in design["elements"].items() if uid in selected}
        selected = expanded


def page_context(design: dict, pid: str) -> dict:
    """Return one canonical page together with its UI subtree and the data bindings used by that subtree."""
    elements = page_elements(design, pid)
    variables = {var for node in elements.values() for var in node["data"]}
    variables.update(node.get("prop", {})["visible"]["var"] for node in elements.values() if isinstance(node.get("prop", {}).get("visible"), dict))
    return {"id": pid, **deepcopy(design["pages"][pid]), "elements": elements,
        "bindings": {var: deepcopy(design["bindings"][var]) for var in sorted(variables) if var in design["bindings"]}}


def owners(design: dict, pid: str) -> list[str]:
    """Return requirements that directly reference elements on this page."""
    ids = set(page_elements(design, pid))
    return [rid for rid, bound in design["requirements"].items() if ids.intersection(bound)]


def visible(design: dict, uid: str, values: dict) -> bool:
    """Evaluate the supported static/variable-equality visibility rule using the supplied display values."""
    visited = set()
    while uid is not None and uid not in visited and uid in design["elements"]:
        visited.add(uid)
        node = design["elements"][uid]
        rule = node.get("prop", {}).get("visible", True)
        if rule is False or (isinstance(rule, dict) and values.get(rule.get("var")) != rule.get("equals")):
            return False
        uid = node.get("parent")
    return True


def normalize_design(design, tree):
    """Fill optional display metadata; accept model decisions without design gates."""
    for pid, page in design["pages"].items():
        page.setdefault("name", pid)
        page.setdefault("images", [])
        page.setdefault("fixtures", {"default": {}})
    for node in design["elements"].values():
        node.setdefault("mode", [])
        node.setdefault("data", [])
        node.setdefault("prop", {})
    for kind, expected in (("requirements", tree.requirements), ("steps", tree.steps)):
        for identity in expected:
            design[kind].setdefault(identity, [])
    return design


def apply_proposal(design, proposal, rid, tree):
    """Replace supplied JSON records without retrieval, immutable-identity or UI-policy gates."""
    updated = deepcopy(design)
    for kind in ("pages", "elements", "bindings"):
        updated[kind].update(deepcopy(proposal[kind]))
    updated["requirements"][rid] = proposal["requirement_ui"]
    updated["steps"].update(deepcopy(proposal["step_ui"]))
    normalize_design(updated, tree)
    return updated
