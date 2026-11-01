"""Incremental entity and field updates."""

from copy import deepcopy


def check_related_fields(schema, fields):
    """Require database associations to resolve before obligation inference consumes them."""
    if not isinstance(fields, list) or any(not isinstance(field, str) for field in fields):
        raise ValueError("related_fields must be an array of qualified Entity.field strings")
    defined = {f"{entity}.{field}" for entity, definition in schema["entities"].items()
        for field in definition["fields"]}
    missing = sorted(set(fields) - defined)
    if missing:
        raise ValueError(
            "related_fields references undefined database fields: " + ", ".join(missing)
            + ". Reuse exact existing names from symbol_inventory, or define the missing entities/fields "
            "in this response's entities update. related_fields does not create definitions; "
            "do not defer them to later requirements."
        )


def apply_patch(schema, patch):
    result = deepcopy(schema)
    for name, update in patch["entities"].items():
        existing = result["entities"].setdefault(name, {"description": "", "fields": {}})
        if "description" in update:
            existing["description"] = update["description"]
        for field, changes in update.get("fields", {}).items():
            existing["fields"].setdefault(field, {}).update(deepcopy(changes))
    return result
