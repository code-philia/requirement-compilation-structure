"""Minimal JSON shape checks; domain acceptance is limited to DB obligations."""


def object_fields(value, fields, label):
    """Require fields and basic JSON types, allowing additional metadata."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    for key, expected in fields.items():
        if key not in value or not isinstance(value[key], expected) or (expected is int and type(value[key]) is not int):
            raise ValueError(f"Invalid JSON shape: {label}.{key}")
    return value


def string_list(value, label):
    """Require an array of strings without imposing uniqueness or semantics."""
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a JSON string array")
    return value
