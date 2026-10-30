"""Complete UI/data output examples, including real elements and variable bindings."""

import json


EXAMPLE = {
    "bindings": {
        "session.state": {"dtype": "string", "constraints": ["unknown, anonymous or authenticated"], "initial": "unknown", "source": "Session result supplied by later trigger logic"},
        "session.username": {"dtype": "string", "constraints": [], "initial": "", "source": "Current user display name supplied by later trigger logic"},
    },
    "elements": {
        "UI-example-home": {"type": "page", "parent": None, "mode": [], "data": [], "prop": {}},
        "UI-example-header": {"type": "container", "parent": "UI-example-home", "mode": [], "data": [], "prop": {}},
        "UI-example-brand": {"type": "heading", "parent": "UI-example-header", "mode": [], "data": [], "prop": {"text": "Example service", "level": 1}},
        "UI-example-register": {"type": "link", "parent": "UI-example-header", "mode": [], "data": [], "prop": {"text": "Register", "href": "/register", "visible": {"var": "session.state", "equals": "anonymous"}}},
        "UI-example-login": {"type": "link", "parent": "UI-example-header", "mode": [], "data": [], "prop": {"text": "Log in", "href": "/login", "visible": {"var": "session.state", "equals": "anonymous"}}},
        "UI-example-username": {"type": "text", "parent": "UI-example-header", "mode": ["user_read"], "data": ["session.username"], "prop": {"visible": {"var": "session.state", "equals": "authenticated"}}},
    },
    "pages": {
        "example-home": {"name": "Example home", "route": "/", "root": "UI-example-home", "images": [],
            "fixtures": {"default": {}, "anonymous": {"session.state": "anonymous"},
                "authenticated": {"session.state": "authenticated", "session.username": "ExampleUser"}}},
    },
    "requirement_ui": ["UI-example-home", "UI-example-header", "UI-example-brand", "UI-example-register", "UI-example-login", "UI-example-username"],
    "step_ui": {
        "STEP-EXAMPLE-ANONYMOUS": ["UI-example-home", "UI-example-register", "UI-example-login"],
        "STEP-EXAMPLE-AUTHENTICATED": ["UI-example-home", "UI-example-username"],
    },
}
REUSE_EXAMPLE = {
    "bindings": {}, "elements": {}, "pages": {},
    "requirement_ui": ["UI-existing-control"], "step_ui": {"STEP-EXAMPLE-REUSE": ["UI-existing-control"]},
}
INSTRUCTIONS = (
    "COMPLETE JSON RESPONSE EXAMPLE FOR A NEW PAGE (all five root sections are written):\n"
    + json.dumps(EXAMPLE, ensure_ascii=False, indent=2)
    + "\nCOMPLETE JSON RESPONSE EXAMPLE FOR REUSE WITHOUT CHANGES:\n"
    + json.dumps(REUSE_EXAMPLE, indent=2)
    + "\nYour final answer must instantiate this five-section structure for the actual requirement. "
    "Define its real controls and variables. Return the entire JSON object, not only pages or fixtures."
)
