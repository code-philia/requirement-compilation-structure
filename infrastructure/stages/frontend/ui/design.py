"""Canonical page/UI/data records and validated incremental design updates."""

from copy import deepcopy

from infrastructure.shared.models.structure import object_fields, string_list


INSTRUCTIONS = """Design UI/data for the current leaf requirement; implementation happens later.
Return exactly {pages:{}, elements:{}, bindings:{}, requirement_ui:[], step_ui:{}}.
Return new or changed records only, with each record COMPLETE. Records replace by ID;
there is no recursive merge, deletion or special patch syntax. Pure reuse needs only
requirement_ui and step_ui references. Preserve previously accepted IDs, routes, roots,
UI types, parents, data references and unrelated props/fixtures when updating a record.
Only retrieved existing pages/elements/bindings may be updated. New IDs must be unique.

Page records have exactly name, route, root, images, fixtures. Routes are concrete paths.
Element records have exactly type, parent, mode, data, prop. A page root has type=page
and parent=null; other nodes reference a parent ID. Supported types are page,container,
form,input,checkbox,select,button,text,heading,link,list,item,image,alert,table.
mode is a list containing user_read and/or user_write, or []. data is a list of VARIABLE
NAMES, not objects. All variable definitions live in bindings, keyed by variable name.
Each binding has exactly dtype, constraints (string list), initial, source (nonempty
origin description). dtype is string,integer,number,boolean,array,object,null. Initial
values must match dtype. No owner fields or duplicated type/constraint descriptors.
Variables may be shared across pages; use explicit stable names. Include frontend-only
state such as errors, selections and loading. Do not expose password hashes or session
credentials; DB fields do not automatically require controls. Document API/input/local
origins in source. Actual production defaults must not be fake backend response data.

prop describes static text,label,placeholder,input_type,options,style,level,href,alt.
Optional prop.visible is a boolean or {var:VARIABLE_NAME,equals:VALUE}; complex decisions
belong to events. Label real inputs and buttons. Checkbox data must reference a boolean.
Every page has fixtures.default={}; add at most max_fixtures other display states,
overriding page variables. Include fixtures making conditional UI visible. Fixtures
are only display-test data. Preserve existing fixtures when replacing a page record.

Design only this requirement's owned content. A navigation destination does not authorize
creating another requirement's forms or behavior. Reuse retrieved pages. requirement_ui
lists directly involved UI IDs. step_ui includes every supplied own step ID exactly once,
using [] for non-UI behavior. Non-UI requirements can return empty records and associations.
Use image.page hints for page IDs and attach provided images to the directly associated
page. Images supply visible layout/labels/style, not hidden business rules. No events,
handlers, executable expressions, implementation code or tests belong in this output.
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


def validate_design(design, tree, images, max_fixtures=None, complete=False):
    """Read UI JSON containers only; do not impose control, scope or design policies."""
    object_fields(design, {key: dict for key in ("pages", "elements", "bindings", "requirements", "steps")}, "UI design")
    for pid, page in design["pages"].items():
        object_fields(page, {"route": str, "root": str}, f"page {pid}")
        page.setdefault("name", pid)
        page.setdefault("images", [])
        page.setdefault("fixtures", {"default": {}})
        object_fields(page, {"name": str, "images": list, "fixtures": dict}, f"page {pid}")
        string_list(page["images"], f"{pid}.images")
        for name, fixture in page["fixtures"].items():
            object_fields(fixture, {}, f"{pid}.fixtures.{name}")
    for uid, node in design["elements"].items():
        object_fields(node, {"type": str, "parent": (str, type(None))}, f"element {uid}")
        node.setdefault("mode", [])
        node.setdefault("data", [])
        node.setdefault("prop", {})
        object_fields(node, {"mode": list, "data": list, "prop": dict}, uid)
        string_list(node["mode"], f"{uid}.mode")
        string_list(node["data"], f"{uid}.data")
    for var, record in design["bindings"].items():
        object_fields(record, {"dtype": str, "constraints": list, "source": str}, f"binding {var}")
        if "initial" not in record:
            raise ValueError(f"Invalid JSON shape: bindings.{var}.initial")
        string_list(record["constraints"], f"{var}.constraints")
    for kind, expected in (("requirements", tree.requirements), ("steps", tree.steps)):
        for identity in expected:
            design[kind].setdefault(identity, [])
        for identity, values in design[kind].items():
            string_list(values, f"{kind}.{identity}")


def apply_proposal(design, proposal, rid, tree, images, retrieved, max_fixtures):
    """Replace supplied JSON records without retrieval, immutable-identity or UI-policy gates."""
    object_fields(proposal, {"pages": dict, "elements": dict, "bindings": dict,
        "requirement_ui": list, "step_ui": dict}, "UI proposal")
    updated = deepcopy(design)
    for kind in ("pages", "elements", "bindings"):
        updated[kind].update(deepcopy(proposal[kind]))
    updated["requirements"][rid] = string_list(proposal["requirement_ui"], "requirement_ui")
    updated["steps"].update(deepcopy(proposal["step_ui"]))
    validate_design(updated, tree, images)
    return updated
