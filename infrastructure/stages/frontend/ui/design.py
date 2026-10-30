"""Canonical UI/data records and incremental design updates."""

from copy import deepcopy



INSTRUCTIONS = """Design a complete UI and its frontend data for the current requirement.
The result is consumed by a component generator: page metadata alone cannot produce
any controls. Design the actual element tree and variables, not just pages or fixtures.
Use requirement scenarios and visual references as evidence; reuse retrieved UI records
where appropriate. This is design only: return no code, tests, triggers or API definitions.

OUTPUT CONTRACT
Return exactly one complete JSON object, with these FIVE SIBLING root keys in this order:
1. bindings: frontend variable definitions.
2. elements: the actual page roots, containers, controls and displayed content.
3. pages: route, root element, image references and display fixture metadata.
4. requirement_ui: element IDs used by the current requirement.
5. step_ui: current scenario step IDs mapped to element IDs.
Write every section in the final JSON content. Mentioning a section in reasoning does
not return it. Do not stop after a page record. Do not nest elements or bindings inside
pages. For a new page, write its root and controls in elements and all variables they
use in bindings. Fixture variables do not create bindings or elements automatically.

RECORD DEFINITIONS
bindings maps VARIABLE NAMES to {dtype, constraints, initial, source}. dtype is a JSON
type name: string, integer, number, boolean, array, object or null. constraints is an
array of descriptions, initial is the application default, and source describes the
origin. Include input, selection, result, loading or error data needed by this UI.

elements maps ELEMENT IDs to {type, parent, mode, data, prop}. A page root has type
"page" and parent=null. Other elements have a parent ELEMENT ID. Use ordinary UI types:
container, form, input, checkbox, select, button, text, heading, link, list, item, image,
alert or table. mode is an array containing user_read and/or user_write, or [].
data is an array of VARIABLE NAMES, not variable objects. prop contains static text,
label, placeholder, input_type, options, style, href, alt or heading level. Optional
prop.visible is a boolean or {var:VARIABLE_NAME, equals:VALUE}. Express business
behavior through triggers later, not expression strings embedded in props.

pages maps PAGE IDs to {name, route, root, images, fixtures}. route is a URL path, root
is an ELEMENT ID, images lists supplied image IDs. fixtures maps display-state names
to variable overrides; include default={} plus representative states within max_fixtures.
Bindings define defaults; fixtures only override them for display tests. Fixture state
must not become an invented production API response. Preserve explicit image.page hints.

requirement_ui is an array of ELEMENT IDs. step_ui maps this requirement's actual step
IDs to arrays of ELEMENT IDs; use [] for a step without UI.

UPDATES AND REUSE
Return complete records for new or changed items. Each supplied record replaces its
previous definition, so preserve unrelated content on shared pages. Unchanged records
can be omitted FROM their maps, but never omit any of the five root keys. Use {} for
an unchanged map, and list reused element IDs in requirement_ui/step_ui. all_pages is
only a page catalogue; retrieved_pages supplies reusable element and variable records.
A requirement without UI returns all five sections with empty maps/lists.

NATIVE INPUT AND SCOPE
The host synchronizes native input/change values for user_write bindings. UI has no
DB obligations or DB field-mapping model. Preserve visible labels in their original
language. Images describe layout and style, not hidden business logic.

The complete example below demonstrates the final response, not an intermediate page
summary. Replace its IDs, labels and state with the current requirement's evidence.
"""


OUTPUT_TEMPLATE = {"bindings": {}, "elements": {}, "pages": {}, "requirement_ui": [], "step_ui": {}}


class UIResponseError(ValueError):
    """Attach the concrete output layout after a model record cannot be consumed."""
    def __init__(self, error, proposal):
        super().__init__(f"Cannot read UI/data response: {error}")
        self.feedback = {"response_template": OUTPUT_TEMPLATE,
            "missing_sections": [key for key in OUTPUT_TEMPLATE if not isinstance(proposal, dict) or key not in proposal],
            "repair": "Write the missing variable and element records in the FINAL JSON, not just in reasoning. Return bindings and elements FIRST, then pages, requirement_ui and step_ui as five sibling root keys. A new page needs its root and controls, their variable definitions and actual scenario associations. Do not repeat the rejected pages-only answer or merely add empty maps for a new page."}


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
