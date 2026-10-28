"""Canonical page/UI/data records and validated incremental design updates."""

from copy import deepcopy
import json
import re
from pathlib import PurePosixPath

from infrastructure.utils.paths import relative_path

NODE_TYPES = {"page", "container", "form", "input", "checkbox", "select", "button", "text", "heading", "link", "list", "item", "image", "alert", "table"}
DATA_TYPES = {"string", "number", "integer", "boolean", "array", "object", "null"}
ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")

INSTRUCTIONS = """Design UI Element (Data) Primitives for the current requirement.
The current requirement is a leaf. Design only the page contents and frontend data
explicitly owned by this leaf. A navigation link to another route does not authorize
creating that destination page's forms, fields, or behavior. Keep the href and reuse
already designed destination UI only when directly involved in the current scenario.
Descriptions identify which sibling requirement owns registration/login submissions;
respect those boundaries. The schema and obligations are data context, not evidence
that every database field needs a control on this leaf's page.
Return sparse updates using the complete ordinary-JSON examples below.
Use normal JSON objects for pages, elements, bindings, props, fixtures, and data.
New pages require route and root. name defaults to the page ID, images to [], and
fixtures to {"default":{}}. Existing pages retain their root and route identities.
Use stable page IDs matching explicit image.page hints where possible. Reuse retrieved
page subtrees before creating another page. Several requirements can share a page;
one requirement can involve several pages. Preserve previous IDs and unrelated nodes.
An input element has type=input, parent=its container ID, mode=[user_write],
a data descriptor, and justified static props such as label/input_type/placeholder.
Types: page,container,form,input,checkbox,select,button,text,heading,link,list,item,image,alert,table.
UI nodes need only fields relevant to the current requirement.
Omit mode, data, or prop when not applicable; consumers treat them as [], [], and {}.
A page root may omit parent and type (inferred as null and page). Other structural nodes
may omit type (inferred as container), but need an existing parent. Provide type for
actual controls. Empty input data is allowed until a binding is designed.
Use prop for static text, label, placeholder, input_type, options (string array), style,
heading level (1..6), href, image alt, and optional visibility. mode is a subset of
[user_read,user_write]; structural elements may use []. data may contain several entries.
Each var has a binding with owner, a type-correct initial value, and nonempty source text.
The owner is a UI ancestor of ALL bound elements. Shared values may have owner=null.
Frontend data is not a copy of DB fields: include confirmPassword, errors, selection,
loading and other local state when required. Record API request/response origins in source;
never add an editable field solely because the DB has a secret/hash/key obligation.
Use dtype string,number,integer,boolean,array,object,null, and string constraint descriptions.
Keep initial values type-correct. Defaults are real initial UI state, not fake API results.
Visibility is either a boolean or {"var":"registration.error","equals":"Example error"}.
For ordinary nonempty error visibility, prefer a boolean local variable such as errorVisible.
Use only this simple equality predicate; complex conditions belong to later events.
fixtures.default must be {}. The compiler-owned default baseline is free; add at most
the supplied max_fixtures named display states per page (so max_fixtures=3 permits
default plus signedOut, signedIn, and loading);
fixtures override named frontend variables only, to render conditional UI without events.
Include fixtures reaching each visibility branch and meaningful list/data display states.
Fixtures are explicit browser-test display data, not production business data.
Every data var needs an element data descriptor and a binding; consistent repeated
bindings reuse the same var/type/constraints. Include structural root nodes as needed.
requirement_ui lists ONLY the current requirement's directly involved UI IDs.
step_ui associates every supplied own step ID with its directly involved UI IDs, including []
for a purely backend step. Do not duplicate child UI mappings into a parent.
No UI requirement may be silently omitted; use explanation for a non-UI requirement.
No triggers/events, executable code, API calls, handlers or interaction implementation
are generated here. Later phases implement those. When creating a new page for an
image with an explicit page hint, include that page root in requirement_ui; the
compiler also binds that root automatically. Images provide layout/labels/style,
not hidden business rules.
"""


def complete_pages(design: dict) -> None:
    """Fill optional page metadata without discarding model-provided extra fields."""
    for pid, page in design["pages"].items():
        if not isinstance(page, dict):
            raise ValueError(f"Page {pid} must be an object, received {type(page).__name__}")
        page.setdefault("name", pid)
        page.setdefault("images", [])
        page.setdefault("fixtures", {})
        if isinstance(page["fixtures"], dict):
            page["fixtures"].setdefault("default", {})
        if "root" not in page and pid in design["elements"]:
            page["root"] = pid
        if "root" not in page or "route" not in page:
            missing = sorted({"root", "route"} - set(page))
            raise ValueError(f"Page {pid} needs routing/tree references {missing}; received {json.dumps(page, ensure_ascii=False)}")


def empty_design() -> dict:
    """Create the initial page, element, binding, and ownership registries with empty interaction slots."""
    return {"pages": {}, "elements": {}, "bindings": {}, "requirements": {}, "steps": {}, "triggers": {}, "events": {}}


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
    variables = {data["var"] for node in elements.values() for data in node.get("data", [])}
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


def validate_design(design: dict, tree, images: dict, max_fixtures: int = 3, complete: bool = False) -> None:
    """Validate page trees, element/data bindings, display fixtures, image references, and requirement/step ownership."""
    if set(design) != set(empty_design()) or any(not isinstance(value, dict) for value in design.values()):
        raise ValueError("UI design needs pages, elements, bindings, requirements, steps, triggers, events objects")
    if design["triggers"] or design["events"]:
        raise ValueError("Step 09 leaves all triggers and events empty")
    complete_pages(design)
    elements, bindings = design["elements"], design["bindings"]
    routes, roots, descriptors, ancestors = set(), set(), {}, {}
    # Validate all shapes before traversing references into other nodes.
    for uid, node in elements.items():
        if not isinstance(uid, str) or not ID.fullmatch(uid) or not isinstance(node, dict):
            raise ValueError(f"Invalid UI identity or node object: {uid}")
        if ("type" in node and (not isinstance(node["type"], str) or node["type"] not in NODE_TYPES)) or (node.get("parent") is not None and not isinstance(node["parent"], str)):
            raise ValueError(f"Invalid UI type/parent: {uid}")
    for uid, node in elements.items():
        if not isinstance(node.get("mode", []), list) or any(not isinstance(mode, str) or mode not in {"user_read", "user_write"} for mode in node.get("mode", [])):
            raise ValueError(f"Invalid UI type/mode: {uid}")
        if not isinstance(node.get("prop", {}), dict) or not isinstance(node.get("data", []), list):
            raise ValueError(f"Invalid UI properties/data: {uid}")
        chain, current = [], uid
        while current is not None:
            if not isinstance(current, str) or current not in elements or current in chain:
                raise ValueError(f"Invalid parent or cycle at {uid}: {current}")
            chain.append(current)
            current = elements[current].get("parent")
        ancestors[uid] = chain
        for data in node.get("data", []):
            if not isinstance(data, dict) or set(data) != {"var", "dtype", "constraints"} or not isinstance(data["var"], str) or not data["var"].strip() or not isinstance(data["dtype"], str) or data["dtype"] not in DATA_TYPES or not isinstance(data["constraints"], list) or any(not isinstance(item, str) for item in data["constraints"]):
                raise ValueError(f"Invalid frontend data descriptor: {uid}")
            var = data["var"]
            if var in descriptors and descriptors[var] != data:
                raise ValueError(f"Inconsistent shared data descriptor: {var}")
            descriptors[var] = data
        if node.get("type") == "checkbox" and node.get("data") and node["data"][0]["dtype"] != "boolean":
            raise ValueError(f"Checkbox data must be boolean: {uid}")
        props = node.get("prop", {})
        for name in ("text", "label", "placeholder", "input_type", "href", "alt"):
            if name in props and not isinstance(props[name], str):
                raise ValueError(f"UI property {name} must be text: {uid}")
        if "options" in props and (not isinstance(props["options"], list) or any(not isinstance(item, str) for item in props["options"])):
            raise ValueError(f"UI options must be strings: {uid}")
        if "level" in props and (type(props["level"]) is not int or not 1 <= props["level"] <= 6):
            raise ValueError(f"Heading level must be 1..6: {uid}")
    if set(bindings) != set(descriptors):
        raise ValueError("Every frontend variable needs a descriptor and exactly one binding")
    for var, binding in bindings.items():
        if not isinstance(binding, dict) or set(binding) != {"owner", "initial", "source"} or not isinstance(binding["source"], str) or not binding["source"].strip():
            raise ValueError(f"Invalid data binding: {var}")
        if not matches_type(binding["initial"], descriptors[var]["dtype"]):
            raise ValueError(f"Initial value does not match dtype: {var}")
        for uid, node in elements.items():
            if any(data["var"] == var for data in node.get("data", [])) and binding["owner"] is not None and binding["owner"] not in ancestors[uid]:
                raise ValueError(f"Data owner must be a shared ancestor, or null for cross-page state: {var}")
    for uid, node in elements.items():
        rule = node.get("prop", {}).get("visible", True)
        if isinstance(rule, dict):
            if set(rule) != {"var", "equals"} or not isinstance(rule["var"], str) or rule["var"] not in bindings or not matches_type(rule["equals"], descriptors[rule["var"]]["dtype"]):
                raise ValueError(f"Invalid visibility predicate: {uid}")
        elif not isinstance(rule, bool):
            raise ValueError(f"Visibility must be boolean or a variable equality: {uid}")
    page_filenames = set()
    for pid, page in design["pages"].items():
        if not isinstance(pid, str) or not ID.fullmatch(pid) or not isinstance(page, dict):
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
        if not isinstance(fixtures, dict) or fixtures.get("default") != {} or not 0 <= named_count <= max_fixtures:
            raise ValueError(f"Provide default={{}} and at most {max_fixtures} named UI fixtures: {pid}")
        subtree = page_elements(design, pid)
        for name, fixture in fixtures.items():
            if not ID.fullmatch(name) or not isinstance(fixture, dict) or any(var not in descriptors or not matches_type(value, descriptors[var]["dtype"]) for var, value in fixture.items()):
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


def merge_properties(previous: dict, patch: dict) -> dict:
    """Merge sparse props/fixture objects without dropping unrelated accepted values."""
    result = deepcopy(previous)
    for name, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(name), dict):
            result[name] = merge_properties(result[name], value)
        else:
            result[name] = deepcopy(value)
    return result


def apply_proposal(design, proposal, rid, tree, images, retrieved, max_fixtures):
    """Merge one requirement's proposal into a copy and validate reuse boundaries and the resulting UI/data graph."""
    expected = {"pages", "elements", "bindings", "requirement_ui", "step_ui", "explanation"}
    if not isinstance(proposal, dict) or set(proposal) != expected or not isinstance(proposal["explanation"], str) or not proposal["explanation"].strip():
        raise ValueError("Return pages, elements, bindings, requirement_ui, step_ui, explanation")
    updated = deepcopy(design)
    for kind in ("pages", "elements", "bindings"):
        if not isinstance(proposal[kind], dict):
            raise ValueError(f"{kind} must be an object")
        for identity, record in proposal[kind].items():
            if not isinstance(record, dict):
                raise ValueError(f"UI {kind} patch must be an object: {identity}")
            previous = updated[kind].get(identity, {})
            merged = {**previous, **deepcopy(record)}
            # Preserve unrelated props and display states when only one changes.
            nested = ("fixtures",) if kind == "pages" else ("prop",) if kind == "elements" else ()
            for name in nested:
                if name in record and isinstance(record[name], dict) and isinstance(previous.get(name), dict):
                    merged[name] = merge_properties(previous[name], record[name])
            updated[kind][identity] = merged
    complete_pages(updated)
    retrieved_ids = {uid for page in retrieved.values() for uid in page["elements"]}
    retrieved_vars = {var for page in retrieved.values() for var in page["bindings"]}
    for kind, allowed in (("pages", set(retrieved)), ("elements", retrieved_ids), ("bindings", retrieved_vars)):
        if (set(proposal[kind]) & set(design[kind])) - allowed:
            raise ValueError(f"Retrieve existing {kind} before modifying them")
    for pid in set(design["pages"]) & set(proposal["pages"]):
        if any(updated["pages"][pid][key] != design["pages"][pid][key] for key in ("root", "route")):
            raise ValueError("Preserve existing page root and route identities")
    if not isinstance(proposal["step_ui"], dict) or set(proposal["step_ui"]) != set(tree.own_steps[rid]):
        raise ValueError("step_ui must include exactly this requirement's own steps")
    updated["requirements"][rid] = deepcopy(proposal["requirement_ui"])
    updated["steps"].update(deepcopy(proposal["step_ui"]))
    validate_design(updated, tree, images, max_fixtures)
    return updated
