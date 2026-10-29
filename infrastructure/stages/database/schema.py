"""Schema JSON structure and incremental updates, without relational policy gates."""

from copy import deepcopy
from infrastructure.shared.models.structure import object_fields, string_list


def validate_schema(schema):
    """Check only the shape needed to read entity/field records."""
    object_fields(schema, {"entities": dict, "requirements": dict}, "schema")
    for name, entity in schema["entities"].items():
        object_fields(entity, {"description": str, "fields": dict}, name)
        for field, record in entity["fields"].items():
            object_fields(record, {"description": str, "type": str, "nullable": bool,
                "primary_key": bool, "unique": bool, "references": (str, type(None)), "constraints": list}, f"{name}.{field}")
            string_list(record["constraints"], f"{name}.{field}.constraints")
    for rid, fields in schema["requirements"].items():
        string_list(fields, f"schema.requirements.{rid}")


def apply_patch(schema, patch, retrieved):
    """Merge JSON records without retrieval, immutable-type or key-policy restrictions."""
    object_fields(patch, {"entities": dict}, "schema proposal")
    result = deepcopy(schema)
    for name, update in patch["entities"].items():
        object_fields(update, {}, name)
        existing = result["entities"].setdefault(name, {"description": "", "fields": {}})
        if "description" in update:
            existing["description"] = update["description"]
        if "fields" in update:
            object_fields(update["fields"], {}, f"{name}.fields")
            for field, changes in update["fields"].items():
                object_fields(changes, {}, f"{name}.{field}")
                existing["fields"].setdefault(field, {}).update(deepcopy(changes))
    validate_schema(result)
    return result
