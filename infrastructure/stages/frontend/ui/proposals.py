"""One complete-record example for step 09; complete records illustrate the protocol."""

import json

EXAMPLE = {
    "pages": {"registration": {"name": "Registration", "route": "/register", "root": "UI-register", "images": [], "fixtures": {"default": {}}}},
    "elements": {
        "UI-register": {"type": "page", "parent": None, "mode": [], "data": [], "prop": {}},
        "UI-username": {"type": "input", "parent": "UI-register", "mode": ["user_write"], "data": ["form.username"], "prop": {"label": "Username", "input_type": "text"}},
    },
    "bindings": {"form.username": {"dtype": "string", "constraints": [], "initial": "", "source": "Local username input"}},
    "requirement_ui": ["UI-register", "UI-username"], "step_ui": {"STEP-EXAMPLE": ["UI-username"]},
}
INSTRUCTIONS = "Complete response example; substitute actual requirement IDs and evidence:\n" + json.dumps(EXAMPLE, indent=2)
