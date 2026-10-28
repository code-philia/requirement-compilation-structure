"""A schema graph: entities own fields; field references form directed edges."""

from copy import deepcopy
import re


IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
FIELD_TYPES = {"string", "integer", "number", "boolean", "date", "datetime", "uuid", "json"}
FIELD_PROPERTIES = {"description", "type", "nullable", "primary_key", "unique", "references", "constraints"}


# --- Extension point: schema language and structural checks -------------------
# Adding field types, properties, or composite keys requires updating both this
# validator and step 02's generation contract. Valid structure alone does not
# establish that the schema satisfies every requirement.
def validate_schema(schema: dict) -> None:
    """Reject malformed symbols and dangling or incompatible reference edges."""
    if not isinstance(schema, dict) or set(schema) != {"entities", "requirements"} or not isinstance(schema["entities"], dict) or not isinstance(schema["requirements"], dict):
        raise ValueError("Schema must contain entities and requirements objects")
    symbols = {}
    for name, entity in schema["entities"].items():
        if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
            raise ValueError(f"Invalid entity name: {name}")
        if not isinstance(entity, dict) or set(entity) != {"description", "fields"}:
            raise ValueError(f"Entity {name} must contain description and fields")
        if not isinstance(entity["description"], str) or not entity["description"].strip():
            raise ValueError(f"Entity description is required: {name}")
        if not isinstance(entity["fields"], dict) or not entity["fields"]:
            raise ValueError(f"Entity must have fields: {name}")
        primary_keys = []
        for field_name, field in entity["fields"].items():
            symbol = f"{name}.{field_name}"
            if not isinstance(field_name, str) or not IDENTIFIER.fullmatch(field_name):
                raise ValueError(f"Invalid field name: {symbol}")
            if not isinstance(field, dict) or set(field) != FIELD_PROPERTIES:
                raise ValueError(f"Field {symbol} must contain {sorted(FIELD_PROPERTIES)}")
            if not isinstance(field["type"], str) or field["type"] not in FIELD_TYPES:
                raise ValueError(f"Unsupported field type: {symbol}")
            if not isinstance(field["description"], str) or not field["description"].strip():
                raise ValueError(f"Field description is required: {symbol}")
            if any(type(field[key]) is not bool for key in ("nullable", "primary_key", "unique")):
                raise ValueError(f"Field flags must be booleans: {symbol}")
            if not isinstance(field["constraints"], list) or any(
                not isinstance(item, str) or not item.strip() for item in field["constraints"]
            ):
                raise ValueError(f"Field constraints must be nonempty strings: {symbol}")
            if field["references"] is not None and not isinstance(field["references"], str):
                raise ValueError(f"Field reference must be a symbol or null: {symbol}")
            if field["primary_key"]:
                primary_keys.append(symbol)
                if field["nullable"]:
                    raise ValueError(f"Primary key must not be nullable: {symbol}")
            symbols[symbol] = field
        if len(primary_keys) != 1:
            raise ValueError(f"Entity must have exactly one primary key: {name}")
    for symbol, field in symbols.items():
        reference = field["references"]
        if reference is None:
            continue
        target = symbols.get(reference)
        if target is None:
            raise ValueError(f"Unknown reference: {symbol} -> {reference}")
        if field["type"] != target["type"]:
            raise ValueError(f"Reference types do not match: {symbol} -> {reference}")
        if not (target["primary_key"] or target["unique"]):
            raise ValueError(f"Reference target must be a primary or unique key: {reference}")
    for rid, related in schema["requirements"].items():
        if not isinstance(rid, str) or not rid.strip() or not isinstance(related, list) or len(related) != len(set(related)):
            raise ValueError(f"Invalid requirement/schema relation: {rid}")
        if any(not isinstance(symbol, str) or symbol not in symbols for symbol in related):
            raise ValueError(f"Requirement relation contains unknown field: {rid}")


# --- Extension point: incremental merge semantics -----------------------------
# This is where reuse becomes a concrete update: preserve omitted properties,
# restrict existing-entity edits to retrieved definitions, then validate a copy.
# Experiments with renaming or deletion must also address downstream symbol use.
def apply_patch(schema: dict, patch: dict, retrieved: dict) -> dict:
    """Merge upserts into a copy; publish only after the entire graph validates."""
    if not isinstance(patch, dict) or set(patch) != {"entities", "explanation"}:
        raise ValueError("Model response must contain entities and explanation")
    if not isinstance(patch["entities"], dict) or not isinstance(patch["explanation"], str):
        raise ValueError("Invalid schema patch")
    result = deepcopy(schema)
    for name, update in patch["entities"].items():
        if not isinstance(update, dict) or set(update) - {"description", "fields"}:
            raise ValueError(f"Invalid entity update: {name}")
        if "fields" in update and not isinstance(update["fields"], dict):
            raise ValueError(f"Updated fields must be an object: {name}")
        existing = result["entities"].get(name)
        if existing is None:
            result["entities"][name] = deepcopy(update)
            continue
        if name not in retrieved:
            raise ValueError(f"Existing entity must be retrieved before modification: {name}")
        if "description" in update:
            existing["description"] = update["description"]
        for field_name, changes in update.get("fields", {}).items():
            if not isinstance(changes, dict):
                raise ValueError(f"Invalid field update: {name}.{field_name}")
            old = existing["fields"].get(field_name)
            if old is not None:
                if "type" in changes and changes["type"] != old["type"]:
                    raise ValueError(f"Cannot change an existing field type: {name}.{field_name}")
                old.update(deepcopy(changes))
            else:
                existing["fields"][field_name] = deepcopy(changes)
    validate_schema(result)
    return result
