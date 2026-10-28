"""Canonical page/UI/data records and validated incremental design updates."""

from copy import deepcopy
import json
import re
from pathlib import PurePosixPath

from infrastructure.utils.paths import relative_path

NODE_TYPES = {"page", "container", "form", "input", "checkbox", "select", "button", "text", "heading", "link", "list", "item", "image", "alert", "table"}
DATA_TYPES = {"string", "number", "integer", "boolean", "array", "object", "null"}
ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")

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
        "bindings": {var: deepcopy(design["bindings"][var]) for var in sorted(variables)}}


def owners(design: dict, pid: str) -> list[str]:
    """Return requirements that directly reference elements on this page."""
    ids = set(page_elements(design, pid))
    return [rid for rid, bound in design["requirements"].items() if ids.intersection(bound)]


def matches_type(value, dtype: str) -> bool:
    """Check a fixture or initial value against the supported frontend data type."""
    if dtype == "null":
        return value is None
    if dtype == "boolean":
        return isinstance(value, bool)
    if dtype in {"number", "integer"}:
        return isinstance(value, (int, float) if dtype == "number" else int) and not isinstance(value, bool)
    return isinstance(value, {"string": str, "array": list, "object": dict}[dtype])


def visible(design: dict, uid: str, values: dict) -> bool:
    """Evaluate the supported static/variable-equality visibility rule using the supplied display values."""
    while uid is not None:
        node = design["elements"][uid]
        rule = node.get("prop", {}).get("visible", True)
        if rule is False or (isinstance(rule, dict) and values[rule["var"]] != rule["equals"]):
            return False
        uid = node.get("parent")
    return True


def validate_design(design: dict, tree, images: dict, max_fixtures: int | None = 3, complete: bool = False) -> None:
    """Validate page trees, element/data bindings, display fixtures, image references, and requirement/step ownership."""
    if not isinstance(design, dict) or set(design) != set(empty_design()) or any(not isinstance(value, dict) for value in design.values()):
        raise ValueError("UI design needs pages, elements, bindings, requirements and steps objects")
    elements, bindings = design["elements"], design["bindings"]
    routes, roots, ancestors = set(), set(), {}
    for var, binding in bindings.items():
        if not isinstance(var, str) or not var.strip() or not isinstance(binding, dict) or set(binding) != {"dtype", "constraints", "initial", "source"}:
            raise ValueError(f"Define each variable once with dtype/constraints/initial/source: {var}")
        if not isinstance(binding["dtype"], str) or binding["dtype"] not in DATA_TYPES or not matches_type(binding["initial"], binding["dtype"]):
            raise ValueError(f"Invalid variable dtype or initial value: {var}")
        if not isinstance(binding["source"], str) or not binding["source"].strip() or not isinstance(binding["constraints"], list) or any(not isinstance(item, str) or not item.strip() for item in binding["constraints"]):
            raise ValueError(f"Invalid variable constraints/source: {var}")
    for uid, node in elements.items():
        if not isinstance(uid, str) or not ID.fullmatch(uid) or not isinstance(node, dict) or set(node) != {"type", "parent", "mode", "data", "prop"}:
            raise ValueError(f"Provide a complete UI element type/parent/mode/data/prop: {uid}")
        if not isinstance(node["type"], str) or node["type"] not in NODE_TYPES or (node["parent"] is not None and not isinstance(node["parent"], str)):
            raise ValueError(f"Invalid UI type/parent: {uid}")
    for uid, node in elements.items():
        if not isinstance(node["mode"], list) or any(not isinstance(mode, str) or mode not in {"user_read", "user_write"} for mode in node["mode"]) or len(set(node["mode"])) != len(node["mode"]):
            raise ValueError(f"Invalid UI mode: {uid}")
        if not isinstance(node["prop"], dict) or not isinstance(node["data"], list) or any(not isinstance(var, str) or var not in bindings for var in node["data"]) or len(set(node["data"])) != len(node["data"]):
            raise ValueError(f"UI data must reference defined variable names: {uid}")
        chain, current = [], uid
        while current is not None:
            if current not in elements or current in chain:
                raise ValueError(f"Invalid parent or cycle at {uid}: {current}")
            chain.append(current)
            current = elements[current]["parent"]
        ancestors[uid] = chain
        if node["type"] == "checkbox" and any(bindings[var]["dtype"] != "boolean" for var in node["data"]):
            raise ValueError(f"Checkbox data must be boolean: {uid}")
        props = node["prop"]
        for name in ("text", "label", "placeholder", "input_type", "href", "alt"):
            if name in props and not isinstance(props[name], str):
                raise ValueError(f"UI property {name} must be text: {uid}")
        if "options" in props and (not isinstance(props["options"], list) or any(not isinstance(item, str) for item in props["options"])):
            raise ValueError(f"UI options must be strings: {uid}")
        if "level" in props and (type(props["level"]) is not int or not 1 <= props["level"] <= 6):
            raise ValueError(f"Heading level must be 1..6: {uid}")
        rule = props.get("visible", True)
        if isinstance(rule, dict):
            if set(rule) != {"var", "equals"} or not isinstance(rule["var"], str) or rule["var"] not in bindings or not matches_type(rule["equals"], bindings[rule["var"]]["dtype"]):
                raise ValueError(f"Invalid visibility predicate: {uid}")
        elif not isinstance(rule, bool):
            raise ValueError(f"Visibility must be boolean or a variable equality: {uid}")
    page_filenames = set()
    for pid, page in design["pages"].items():
        if not isinstance(pid, str) or not ID.fullmatch(pid) or not isinstance(page, dict) or set(page) != {"name", "route", "root", "images", "fixtures"}:
            raise ValueError(f"Invalid page identity or page object: {pid}")
        relative_path(f"frontend/tests/ui/{pid}.spec.ts")
        if pid.casefold() in page_filenames:
            raise ValueError(f"Page IDs must not differ only in filename case: {pid}")
        page_filenames.add(pid.casefold())
        if not isinstance(page.get("name", pid), str) or not page.get("name", pid).strip():
            raise ValueError(f"Page {pid}: name must be nonempty text")
        if "root" not in page or "route" not in page:
            raise ValueError(f"Page {pid} needs root and route references")
        route = page["route"]
        if not isinstance(route, str) or not route.startswith("/") or route.startswith("//") or any(char in route for char in ("?", "#", "\\")) or ".." in PurePosixPath(route).parts or (route != "/" and route.endswith("/")) or route in routes:
            raise ValueError(f"Use a unique concrete page route without query/hash/trailing slash: {pid}")
        routes.add(route)
        root = page["root"]
        if not isinstance(root, str) or root not in elements or elements[root].get("parent") is not None or elements[root].get("type", "page") != "page" or root in roots:
            raise ValueError(f"A page needs its own page root: {pid}")
        roots.add(root)
        if elements[root].get("prop", {}).get("visible", True) is not True:
            raise ValueError(f"Page roots must always be visible: {pid}")
        if not isinstance(page["images"], list) or any(not isinstance(image, str) or image not in images for image in page["images"]):
            raise ValueError(f"Unknown image reference: {pid}")
        fixtures = page["fixtures"]
        named_count = len(fixtures) - 1 if isinstance(fixtures, dict) and "default" in fixtures else -1
        if not isinstance(fixtures, dict) or fixtures.get("default") != {} or (named_count < 0 or (max_fixtures is not None and named_count > max_fixtures)):
            raise ValueError(f"Provide default={{}} and at most {max_fixtures} named UI fixtures: {pid}")
        subtree = page_elements(design, pid)
        for name, fixture in fixtures.items():
            if not isinstance(name, str) or not ID.fullmatch(name) or not isinstance(fixture, dict) or any(var not in bindings or not matches_type(value, bindings[var]["dtype"]) for var, value in fixture.items()):
                raise ValueError(f"Invalid display fixture: {pid}/{name}")
        defaults = {var: binding["initial"] for var, binding in bindings.items()}
        for uid in subtree:
            rule = elements[uid].get("prop", {}).get("visible", True)
            if isinstance(rule, dict) and not any(visible(design, uid, defaults | fixture) for fixture in fixtures.values()):
                raise ValueError(f"Add a fixture reaching conditional UI: {pid}/{uid}")
    if any(chain[-1] not in roots for chain in ancestors.values()):
        raise ValueError("Every UI element must belong to one registered page")
    for kind, allowed in (("requirements", tree.requirements), ("steps", tree.steps)):
        if complete and set(design[kind]) != set(allowed):
            raise ValueError(f"UI design must account for every {kind} ID")
        for identity, ids in design[kind].items():
            if identity not in allowed or not isinstance(ids, list) or any(not isinstance(uid, str) or uid not in elements for uid in ids) or len(set(ids)) != len(ids):
                raise ValueError(f"Invalid {kind}-to-UI association: {identity}")
    for sid, ids in design["steps"].items():
        rid = next(rid for rid, steps in tree.own_steps.items() if sid in steps)
        if not set(ids).issubset(design["requirements"].get(rid, [])):
            raise ValueError(f"Step UI must be included in its requirement's direct UI set: {sid}")
    if complete and any(not owners(design, pid) for pid in design["pages"]):
        raise ValueError("Every page needs a directly associated requirement")
    json.dumps(design, allow_nan=False)


def apply_proposal(design, proposal, rid, tree, images, retrieved, max_fixtures):
    """Replace complete records by ID; retain all other records and accepted associations."""
    expected = {"pages", "elements", "bindings", "requirement_ui", "step_ui"}
    if not isinstance(proposal, dict) or set(proposal) != expected:
        raise ValueError(f"Return exactly {sorted(expected)}")
    updated = deepcopy(design)
    allowed = {"pages": set(retrieved),
        "elements": {uid for page in retrieved.values() for uid in page["elements"]},
        "bindings": {var for page in retrieved.values() for var in page["bindings"]}}
    for kind in ("pages", "elements", "bindings"):
        if not isinstance(proposal[kind], dict):
            raise ValueError(f"{kind} must be an object of complete records")
        if (set(proposal[kind]) & set(design[kind])) - allowed[kind]:
            raise ValueError(f"Retrieve existing {kind} before modifying them")
        updated[kind].update(deepcopy(proposal[kind]))
    if not isinstance(proposal["step_ui"], dict) or set(proposal["step_ui"]) != set(tree.own_steps[rid]):
        raise ValueError("step_ui must include exactly this requirement's own step IDs")
    updated["requirements"][rid] = deepcopy(proposal["requirement_ui"])
    updated["steps"].update(deepcopy(proposal["step_ui"]))
    validate_design(updated, tree, images, max_fixtures)
    for pid in set(design["pages"]) & set(proposal["pages"]):
        before, after = design["pages"][pid], updated["pages"][pid]
        if not isinstance(after, dict) or any(after.get(key) != before[key] for key in ("root", "route")):
            raise ValueError("Preserve existing page root and route identities")
        if not set(before["images"]).issubset(after.get("images", [])) or not set(before["fixtures"]).issubset(after.get("fixtures", {})):
            raise ValueError("Preserve accepted page images and fixture names")
    for uid in set(design["elements"]) & set(proposal["elements"]):
        before, after = design["elements"][uid], updated["elements"][uid]
        if not isinstance(after, dict) or any(after.get(key) != before[key] for key in ("type", "parent")):
            raise ValueError("Preserve existing UI types and parents")
        if not isinstance(after.get("prop"), dict) or not isinstance(after.get("data"), list) or not set(before["prop"]).issubset(after["prop"]) or not set(before["data"]).issubset(after["data"]):
            raise ValueError("Preserve unrelated accepted UI props and data references")
    for var in set(design["bindings"]) & set(proposal["bindings"]):
        if not isinstance(updated["bindings"][var], dict) or updated["bindings"][var].get("dtype") != design["bindings"][var]["dtype"]:
            raise ValueError(f"Preserve accepted variable types: {var}")
    return updated
