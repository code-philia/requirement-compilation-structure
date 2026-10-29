"""Validate obligations against the existing database symbol space."""

from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.shared.models.structure import object_fields


def field_symbols(schema: dict) -> set[str]:
    """Enumerate the canonical Entity.field symbols that obligations are allowed to reference."""
    return {f"{entity}.{field}" for entity, value in schema["entities"].items() for field in value["fields"]}


def validate_record(record: dict, symbols: set[str], label: str) -> dict:
    """Validate one read/write record against known fields and return sorted, deduplicated sets."""
    object_fields(record, {"read": list, "write": list}, label)
    result = {}
    for mode in ("read", "write"):
        fields = record[mode]
        if not isinstance(fields, list) or any(not isinstance(field, str) for field in fields):
            raise ValueError(f"{label}.{mode} must be a list of field symbols")
        unknown = set(fields) - symbols
        if unknown:
            raise ValueError(f"Unknown schema symbols in {label}.{mode}: {sorted(unknown)}")
        result[mode] = sorted(set(fields))
    return result


# --- Extension point: the model-to-obligation contract -------------------------
# If inference gains evidence or another obligation kind, update this boundary
# and its consumers together. Unknown DB field symbols are errors;
# these checks do not establish semantic completeness or containment coverage.
def validate_inference(result: dict, symbols: set[str], step_ids: list[str]) -> dict:
    """Validate a model proposal for one requirement and all its own steps; retain field-symbol checks."""
    object_fields(result, {"requirement": dict, "steps": dict}, "obligation proposal")
    return {"requirement": validate_record(result["requirement"], symbols, "requirement"),
        "steps": {sid: validate_record(result["steps"].get(sid, {"read": [], "write": []}), symbols, sid) for sid in step_ids}}


def validate_obligations(value: dict, tree: RequirementTree, symbols: set[str]) -> dict:
    """Validate complete requirement/step coverage and return normalized obligations using the existing schema symbols."""
    object_fields(value, {"requirements": dict, "steps": dict}, "obligations")
    result = {}
    for kind, expected in (("requirements", tree.requirements), ("steps", tree.steps)):
        result[kind] = {key: validate_record(value[kind].get(key, {"read": [], "write": []}), symbols, key) for key in expected}
    return result
