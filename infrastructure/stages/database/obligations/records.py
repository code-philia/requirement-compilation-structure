"""Validate obligations against the existing database symbol space."""

from infrastructure.stages.requirements.tree import RequirementTree


def field_symbols(schema: dict) -> set[str]:
    """Enumerate the canonical Entity.field symbols that obligations are allowed to reference."""
    return {f"{entity}.{field}" for entity, value in schema["entities"].items() for field in value["fields"]}


def validate_record(record: dict, symbols: set[str], label: str) -> dict:
    """Validate one read/write record against known fields and return sorted, deduplicated sets."""
    if not isinstance(record, dict) or set(record) != {"read", "write"}:
        raise ValueError(f"{label} must contain exactly read and write")
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
# and its consumers together. Unknown symbols and unmapped concepts are errors;
# these checks do not establish semantic completeness or containment coverage.
def validate_inference(result: dict, symbols: set[str], step_ids: list[str]) -> dict:
    """Validate a model proposal for one requirement and all its own steps; reject unmapped data concepts."""
    if not isinstance(result, dict) or set(result) != {"requirement", "steps", "explanation", "unmapped"}:
        raise ValueError("Inference must contain requirement, steps, explanation, and unmapped")
    if not isinstance(result["explanation"], str) or not result["explanation"].strip():
        raise ValueError("Inference explanation must be nonempty text")
    if not isinstance(result["unmapped"], list) or any(not isinstance(item, str) for item in result["unmapped"]):
        raise ValueError("unmapped must be a list of data concepts")
    if result["unmapped"]:
        raise ValueError(f"Data concepts cannot be mapped to this schema: {result['unmapped']}")
    if not isinstance(result["steps"], dict) or set(result["steps"]) != set(step_ids):
        raise ValueError(f"Return exactly these step IDs: {step_ids}")
    return {
        "requirement": validate_record(result["requirement"], symbols, "requirement"),
        "steps": {sid: validate_record(result["steps"][sid], symbols, sid) for sid in step_ids},
    }


def validate_obligations(value: dict, tree: RequirementTree, symbols: set[str]) -> dict:
    """Validate complete requirement/step coverage and return normalized obligations using the existing schema symbols."""
    if not isinstance(value, dict) or set(value) != {"requirements", "steps"}:
        raise ValueError("Obligations must contain exactly requirements and steps")
    result = {}
    for kind, expected in (("requirements", tree.requirements), ("steps", tree.steps)):
        if not isinstance(value[kind], dict) or set(value[kind]) != set(expected):
            raise ValueError(f"Obligation IDs do not match the requirement tree: {kind}")
        result[kind] = {key: validate_record(value[kind][key], symbols, key) for key in expected}
    return result
