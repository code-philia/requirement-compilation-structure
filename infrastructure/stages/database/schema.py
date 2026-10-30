"""Incremental entity and field updates."""

from copy import deepcopy


def apply_patch(schema, patch):
    result = deepcopy(schema)
    for name, update in patch["entities"].items():
        existing = result["entities"].setdefault(name, {"description": "", "fields": {}})
        if "description" in update:
            existing["description"] = update["description"]
        for field, changes in update.get("fields", {}).items():
            existing["fields"].setdefault(field, {}).update(deepcopy(changes))
    return result
