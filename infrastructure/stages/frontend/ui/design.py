"""Canonical UI/data records and incremental design updates."""

from copy import deepcopy



INSTRUCTIONS = """Design UI and frontend data for the supplied leaf requirement, using scenarios,
visual references and retrieved page subtrees. Return one JSON object with all five
top-level sections: {"pages":{},"elements":{},"bindings":{},"requirement_ui":[],"step_ui":{}}.
Return complete new or changed records INSIDE these sections. For an unchanged map,
return {} rather than omitting its section. requirement_ui still lists reused element
IDs. Updates replace records, so retain unrelated content on shared pages.
pages contains page metadata only; it does not define the page's controls or data.
A new page also needs its root and controls in elements, and its variables in
bindings. A page listed in all_pages is only a catalogue entry; reuse complete
records from retrieved_pages when supplied.

pages maps PAGE IDs to {name, route, root, images, fixtures}. route is a URL path;
root is an ELEMENT ID; images lists supplied image IDs. These IDs have different roles.
fixtures maps display-state names to frontend variable overrides. Include default={}
and representative states within the supplied max_fixtures named-state target.
Fixtures supply display-test values; initial variables supply application defaults.

elements maps ELEMENT IDs to {type, parent, mode, data, prop}. A page root has type
"page" and parent=null; other elements reference a parent element ID. Use ordinary
UI types such as container, form, input, checkbox, select, button, text, heading, link,
list, item, image, alert or table. mode is an array whose entries are "user_read" or
"user_write", such as [], ["user_write"] or ["user_read","user_write"]. data is an
array of frontend VARIABLE NAMES, for example ["form.username"], not variable objects.
prop holds static text, label, placeholder, input_type, options, style, href, alt or
heading level. Optional prop.visible is a boolean or {var:VARIABLE_NAME, equals:VALUE}.
Business decisions are expressed by triggers later, not expression strings in prop.

bindings defines variables once, keyed by name, as {dtype, constraints, initial, source}.
dtype is a string naming a JSON type: "string", "integer", "number", "boolean",
"array", "object" or "null".
constraints is an array of descriptions; initial is the default value; source describes
the origin. Include input, result, selection, loading or error state required by the UI.
Native editable values are synchronized by the host. UI has no DB obligations or DB
field-mapping model. Do not make fixture data into invented production responses.

requirement_ui lists elements used by this requirement. step_ui maps its scenario
step IDs to element lists, with [] for steps without UI. Non-UI requirements can
return empty records and lists. Preserve visible text in its original language;
images provide layout/style evidence, not hidden business rules. Use supplied image.page
hints for page IDs. Do not return triggers, handlers, code or tests.
"""


OUTPUT_TEMPLATE = {"pages": {}, "elements": {}, "bindings": {}, "requirement_ui": [], "step_ui": {}}


class UIResponseError(ValueError):
    """Attach the concrete output layout after a model record cannot be consumed."""
    def __init__(self, error, proposal):
        super().__init__(f"Cannot read UI/data response: {error}")
        self.feedback = {"response_template": OUTPUT_TEMPLATE,
            "missing_sections": [key for key in OUTPUT_TEMPLATE if not isinstance(proposal, dict) or key not in proposal],
            "repair": "Return the complete five-section UI response. pages alone is incomplete. Define new page roots and controls in elements, variables in bindings, and requirement/step associations in requirement_ui and step_ui. Existing records may be reused by ID; missing new records must be written. Do not repeat the rejected pages-only response."}


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
