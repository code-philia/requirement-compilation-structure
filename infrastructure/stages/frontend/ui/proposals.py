"""Example-guided incremental UI proposals with local validation only.

The model returns the same ordinary JSON dictionaries used by the design merger.
No server-side JSON Schema support or special value encoding is required.
"""

from copy import deepcopy
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from infrastructure.stages.frontend.ui.design import DATA_TYPES, NODE_TYPES


# Each example is a complete response; the model substitutes actual retrieved IDs
# and step IDs. Serialize examples in Python so their JSON syntax stays valid.
EXAMPLES = [
    ("Create a new registration page with one local username input.", {
        "pages": {"registration": {"route": "/register", "root": "UI-register"}},
        "elements": {
            "UI-register": {"type": "page", "parent": None},
            "UI-username": {"type": "input", "parent": "UI-register", "mode": ["user_write"],
                "data": [{"var": "registration.username", "dtype": "string", "constraints": []}],
                "prop": {"label": "Username", "input_type": "text"}},
        },
        "bindings": {"registration.username": {"owner": "UI-register", "initial": "", "source": "Local username input"}},
        "requirement_ui": ["UI-username"], "step_ui": {"STEP-EXAMPLE": ["UI-username"]},
        "explanation": "Create only the page and input justified by this requirement.",
    }),
    ("The retrieved page already has every needed UI element and binding; reuse it unchanged.", {
        "pages": {}, "elements": {}, "bindings": {},
        "requirement_ui": ["UI-username"], "step_ui": {"STEP-EXAMPLE": ["UI-username"]},
        "explanation": "Reuse the retrieved username input without repeating its definition.",
    }),
    ("On the retrieved registration page, change a label and add one filled display fixture.", {
        "pages": {"registration": {"fixtures": {"filled": {"registration.username": "example_user"}}}},
        "elements": {"UI-username": {"prop": {"label": "Account name"}}}, "bindings": {},
        "requirement_ui": ["UI-username"], "step_ui": {"STEP-EXAMPLE": ["UI-username"]},
        "explanation": "Change only the label and new fixture; retain existing input props and display states.",
    }),
]

INSTRUCTIONS = """Return ONE small incremental JSON object with exactly these six keys:
pages, elements, bindings, requirement_ui, step_ui, explanation.
pages/elements/bindings are dictionaries keyed by ID or variable name. step_ui is
a dictionary keyed by actual supplied step IDs; include every own step exactly once.
Use ordinary JSON values throughout. Do not return patches, fields, or entries arrays.
Do not put JSON inside strings. Return no Markdown fences or surrounding explanation.
Keep all six keys inside the SAME outer object; close that object after explanation.

Only return fields that add or change accepted state. Preserve IDs from retrieved
pages and do not recreate their headers, navigation, inputs, or bindings. For pure
reuse, return empty pages/elements/bindings and associate existing IDs in the two
UI mappings. A field with no actual change is rejected; omit it instead of copying it.
Existing fields omitted from a patch are retained. prop merges by property; fixtures
merge by state name and variable. Include only the new/changed properties or states.
Arrays replace their entire field. A binding's initial value replaces that entire
value. No deletion operation is provided. New records still need their necessary
fields, descriptors, and bindings, as demonstrated by the first example.

The following are independent, COMPLETE valid examples. They are formatting and
reuse examples, not additional requirements. Substitute current retrieved IDs and
actual supplied step IDs; never copy STEP-EXAMPLE into the real response.
""" + "\n\n".join(f"Example {number}: {description}\n{json.dumps(value, indent=2)}"
    for number, (description, value) in enumerate(EXAMPLES, 1)) + """

When correcting an error, return the COMPLETE corrected incremental proposal
relative to the unchanged accepted design, including earlier proposed new records.
Never return a partial response containing only the corrected field.
"""


def object_schema(properties: dict, required=None) -> dict:
    """Build a closed object schema for local validation, optionally allowing sparse fields."""
    return {"type": "object", "properties": properties,
        "required": list(properties) if required is None else required, "additionalProperties": False}


def proposal_schema(step_ids: list[str]) -> dict:
    """Check ordinary JSON dictionaries locally; this schema is never sent to the provider."""
    strings = {"type": "array", "items": {"type": "string"}}
    nullable_id = {"type": ["string", "null"]}
    descriptor = object_schema({"var": {"type": "string"},
        "dtype": {"enum": sorted(DATA_TYPES)}, "constraints": strings})
    page = object_schema({"route": {"type": "string"}, "root": {"type": "string"},
        "name": {"type": "string"}, "images": strings,
        "fixtures": {"type": "object", "additionalProperties": {"type": "object"}}}, required=[])
    element = object_schema({"type": {"enum": sorted(NODE_TYPES)}, "parent": nullable_id,
        "mode": {"type": "array", "items": {"enum": ["user_read", "user_write"]}},
        "data": {"type": "array", "items": descriptor}, "prop": {"type": "object"}}, required=[])
    binding = object_schema({"owner": nullable_id, "initial": {}, "source": {"type": "string"}}, required=[])
    return object_schema({
        "pages": {"type": "object", "additionalProperties": page},
        "elements": {"type": "object", "additionalProperties": element},
        "bindings": {"type": "object", "additionalProperties": binding},
        "requirement_ui": strings,
        "step_ui": object_schema({sid: strings for sid in step_ids}),
        "explanation": {"type": "string", "minLength": 1},
    })


def changed_fields(before: dict, patch: dict) -> dict:
    """Keep only changed object entries; arrays and scalar values are replaced atomically."""
    result = {}
    for key, value in patch.items():
        if key not in before:
            result[key] = deepcopy(value)
        elif isinstance(value, dict) and isinstance(before[key], dict):
            nested = changed_fields(before[key], value)
            if nested:
                result[key] = nested
        elif before[key] != value or type(before[key]) is not type(value):
            result[key] = deepcopy(value)
    return result


def validate_proposal(response: dict, design: dict, step_ids: list[str]) -> dict:
    """Validate shape and sparse updates before semantic graph validation or publication."""
    try:
        Draft202012Validator(proposal_schema(step_ids)).validate(response)
    except ValidationError as error:
        location = "/".join(str(part) for part in error.absolute_path) or "(root)"
        raise ValueError(f"Invalid UI proposal at {location}: {error.message}") from error
    for target in ("pages", "elements", "bindings"):
        for identity, fields in response[target].items():
            if not fields:
                raise ValueError(f"Omit empty UI patches: {target}/{identity}")
            before = design[target].get(identity, {})
            changes = {name: value for name, value in fields.items()
                if name not in before or before[name] != value or type(before[name]) is not type(value)}
            # Only props and fixtures have nested merge semantics. In particular,
            # an object-valued binding initial state is one atomic replacement.
            for name in ("prop", "fixtures"):
                if name in fields and isinstance(fields[name], dict) and isinstance(before.get(name), dict):
                    changes.pop(name, None)
                    nested = changed_fields(before[name], fields[name])
                    if nested:
                        changes[name] = nested
            if changes != fields:
                delta = json.dumps(changes, ensure_ascii=False)
                raise ValueError(f"Omit unchanged fields/properties in {target}/{identity}; send only this delta: {delta}")
    return deepcopy(response)
