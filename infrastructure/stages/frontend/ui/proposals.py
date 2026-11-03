"""UI design examples with variable declarations inside elements."""

import json


EXAMPLE = {
    "elements": {
        "UI-home": {"type": "page", "parent": None, "mode": [], "data": [], "prop": {}},
        "UI-search": {"type": "input", "parent": "UI-home", "mode": ["user_write"],
            "data": [{"var": "search.query", "dtype": "string", "constraints": []}],
            "prop": {"label": "Search"}},
        "UI-results": {"type": "list", "parent": "UI-home", "mode": ["user_read"],
            "data": [{"var": "search.results", "dtype": "array",
                "constraints": ["Entries contain id and title strings and match the submitted query"]}], "prop": {}},
    },
    "pages": {"home": {"name": "Home", "route": "/", "root": "UI-home", "images": []}},
    "requirement_ui": ["UI-home", "UI-search", "UI-results"],
    "step_ui": {"STEP-search": ["UI-search", "UI-results"]},
}
REUSE_EXAMPLE = {"elements": {}, "pages": {}, "requirement_ui": ["UI-search"],
    "step_ui": {"STEP-reuse": ["UI-search"]}}
INSTRUCTIONS = (
    "COMPLETE UI DECLARATION EXAMPLE:\n" + json.dumps(EXAMPLE, ensure_ascii=False, indent=2)
    + "\nREUSE WITHOUT CHANGES:\n" + json.dumps(REUSE_EXAMPLE, indent=2)
    + "\nReturn all four sections. Variables belong in element.data; do not add runtime values."
)
