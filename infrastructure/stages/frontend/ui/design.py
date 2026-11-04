"""Canonical UI/data records and incremental design updates."""

from copy import deepcopy



INSTRUCTIONS = """Design the UI elements and frontend data declarations for the current requirement.
Use requirement scenarios and visual references; reuse supplied UI elements where appropriate.
This stage declares the interface only. Return no code, tests, API definitions, triggers,
production initial values, example runtime objects or display fixtures.

OUTPUT CONTRACT
Return one JSON object with four sibling keys: elements, pages, requirement_ui, step_ui.
elements maps ELEMENT IDs to {type, parent, mode, data, prop}. A page root has type
"page" and parent=null. Other elements reference a parent ELEMENT ID. Use ordinary types:
container, form, input, checkbox, select, button, text, heading, link, list, item, image,
alert or table. mode is an array containing user_read and/or user_write, or [].

data is an array of variable declarations: {var, dtype, constraints}.
var is the frontend variable name; dtype is string, integer, number, boolean, array,
object or null. constraints describes requirement-based rules and any array/object shape.
Declare all dynamic data consumed by the element, including visibility dependencies.
Repeat the same declaration consistently when several elements share a variable.
Do not produce a separate bindings registry or initial/source fields.
Fixed headings, labels, hints and button captions belong in prop, not dynamic data.
prop contains static text, label, placeholder, input_type, options, style, href, alt
or heading level. Optional prop.visible is a boolean or {var:VARIABLE_NAME, equals:VALUE}.
A status dependency controls visibility without requiring its raw value as display text.

Treat explicit UI names and roles in the original requirement as interface contracts.
Preserve required labels, action names, region names and placeholders verbatim, including
language, spelling and case. Do not paraphrase, add object-type prefixes, translate or
concatenate aliases: a required "Name" field must not become "Shelf name". Record the
wording in the existing element.prop; do not create a separate naming registry.
Explicit requirement wording takes precedence over visual-reference examples. Only choose
wording freely when it is unspecified or alternatives are explicitly allowed. Business
record names and user-entered values remain dynamic; example data is not fixed UI wording.

pages maps PAGE IDs to {name, route, root, images}. route is a URL path, root is an
ELEMENT ID and images lists supplied image IDs. Preserve explicit image.page hints.
Do not add fixtures or sample objects. Reference images describe appearance, not actual
loaded records. Requirement-defined defaults remain requirement evidence for implementation;
do not turn them into a separate initialization model in this design.
requirement_ui lists element IDs used by the current requirement. step_ui maps every
current scenario step ID to element IDs, using [] when no UI is needed.

UPDATES AND REUSE
Return complete records for new or changed elements/pages, preserving unrelated behavior.
Unchanged records may be omitted from their maps; include all four root keys even when empty.
Reuse canonical variable names and element IDs. Query relevant elements/pages when needed.
mode declares how the user interacts with the element; implementation chooses framework
bindings and routing. No fixed host synchronizes inputs or interprets this design. Additional
interaction behavior belongs to step 09; real data loading and updates belong to step 10.
Preserve visible labels in their original language. UI has no DB field-mapping model.
"""

OUTPUT_TEMPLATE = {"elements": {}, "pages": {}, "requirement_ui": [], "step_ui": {}}


class UIResponseError(ValueError):
    """Attach the concrete output layout after a model record cannot be consumed."""
    def __init__(self, error, proposal):
        super().__init__(f"Cannot read UI/data response: {error}")
        self.feedback = {"response_template": OUTPUT_TEMPLATE,
            "missing_sections": [key for key in OUTPUT_TEMPLATE if not isinstance(proposal, dict) or key not in proposal],
            "repair": "Write the missing variable and element records in the FINAL JSON, not just in reasoning. Return elements, pages, requirement_ui and step_ui as four sibling root keys. Declare variables inside element.data. A new page needs its root, controls and actual scenario associations. Do not repeat the rejected pages-only answer or merely add empty maps for a new page."}


def empty_design() -> dict:
    """Keep UI elements, pages and requirement associations."""
    return {"pages": {}, "elements": {}, "requirements": {}, "steps": {}}


def page_elements(design: dict, pid: str) -> dict:
    """Return the IDs in one page's UI subtree, including its root."""
    root = design["pages"][pid]["root"]
    selected = {root}
    while True:
        expanded = selected | {uid for uid, node in design["elements"].items() if node.get("parent") in selected}
        if expanded == selected:
            return {uid: deepcopy(node) for uid, node in design["elements"].items() if uid in selected}
        selected = expanded


def data_symbols(elements: dict) -> dict:
    """Derive a variable lookup from element declarations without storing another registry."""
    symbols = {}
    for element in elements.values():
        for declaration in element.get("data", []):
            symbols[declaration["var"]] = deepcopy(declaration)
    return symbols


def page_context(design: dict, pid: str) -> dict:
    """Return a page and its UI subtree, including inline variable declarations."""
    return {"id": pid, **deepcopy(design["pages"][pid]), "elements": page_elements(design, pid)}


def requirement_ui(design: dict, requirement_ids: list[str]) -> dict:
    """Select directly owned UI nodes and their ancestor structure, never future siblings."""
    selected = set()
    for rid in requirement_ids:
        for uid in design["requirements"].get(rid, []):
            current = uid
            ancestors = set()
            while current is not None and current not in selected:
                if current in ancestors:
                    raise ValueError(f"UI parent cycle for {rid}: {current}")
                if current not in design["elements"]:
                    raise ValueError(f"Unknown UI element for {rid}: {current}")
                ancestors.add(current)
                current = design["elements"][current].get("parent")
            selected.update(ancestors)
    return {
        **design,
        "pages": {pid: deepcopy(page) for pid, page in design["pages"].items()
            if page["root"] in selected},
        "elements": {uid: deepcopy(node) for uid, node in design["elements"].items()
            if uid in selected},
    }


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
    """Fill optional page metadata; accept model decisions without design gates."""
    for pid, page in design["pages"].items():
        page.setdefault("name", pid)
        page.setdefault("images", [])
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
    for kind in ("pages", "elements"):
        updated[kind].update(deepcopy(proposal[kind]))
    updated["requirements"][rid] = proposal["requirement_ui"]
    updated["steps"].update(deepcopy(proposal["step_ui"]))
    normalize_design(updated, tree)
    return updated
