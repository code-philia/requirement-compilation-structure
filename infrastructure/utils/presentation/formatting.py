"""Pure text views of schemas, obligations, API inventories, and coverage gaps."""


def field_lines(name: str, field: dict, details: bool = True) -> list[str]:
    """Render a field's type, key/nullability/reference flags, and optional description and constraints."""
    flags = [label for key, label in (("primary_key", "PK"), ("unique", "UNIQUE")) if field[key]]
    flags.append("NULL" if field["nullable"] else "NOT NULL")
    if field["references"]:
        flags.append(f"-> {field['references']}")
    lines = [f"  {name:<24} {field['type']:<10} {', '.join(flags)}"]
    if details:
        lines.append(f"    {field['description']}")
        lines.extend(f"    Constraint: {item}" for item in field["constraints"])
    return lines


def format_schema(entities: dict, excerpt: bool = False) -> str:
    """Render entity/field definitions, optionally truncating the inventory for a classroom overview."""
    if not entities:
        return "(No entities yet.)"
    lines = []
    items = list(entities.items())
    for name, entity in (items[:6] if excerpt else items):
        lines.extend([f"{name} — {entity['description']}", "  FIELD                    TYPE       PROPERTIES"])
        fields = list(entity["fields"].items())
        for field_name, field in (fields[:6] if excerpt else fields):
            lines.extend(field_lines(field_name, field, details=not excerpt))
        if excerpt and len(fields) > 6:
            lines.append(f"  ... {len(fields) - 6} more fields")
        lines.append("")
    if excerpt and len(items) > 6:
        lines.append(f"... {len(items) - 6} more entities")
    return "\n".join(lines)


def format_changes(before: dict, after: dict) -> str:
    """Describe new entities and changed fields by comparing two accepted schema snapshots."""
    lines = []
    for name, entity in after["entities"].items():
        old = before["entities"].get(name)
        if old is None:
            lines.extend([f"NEW ENTITY: {name}", format_schema({name: entity})])
            continue
        if old == entity:
            continue
        lines.append(f"UPDATED ENTITY: {name}")
        if old["description"] != entity["description"]:
            lines.append(f"  Description: {old['description']} -> {entity['description']}")
        for field_name, field in entity["fields"].items():
            previous = old["fields"].get(field_name)
            if previous == field:
                continue
            if previous is None:
                lines.append(f"  ADDED FIELD: {name}.{field_name}")
                lines.extend(field_lines(field_name, field))
            else:
                lines.append(f"  UPDATED FIELD: {name}.{field_name}")
                for key, value in field.items():
                    if previous[key] != value:
                        lines.append(f"    {key}: {previous[key]!r} -> {value!r}")
    return "\n".join(lines) or "No changes: the existing schema is reused."


def format_obligations(records: dict, empty_label: str = "(empty)") -> str:
    """Render independent READ and WRITE field lists for requirement, step, or API records."""
    lines = []
    for node_id, record in records.items():
        lines.append(node_id)
        lines.append("  READ : " + (", ".join(record["read"]) or empty_label))
        lines.append("  WRITE: " + (", ".join(record["write"]) or empty_label))
        lines.append("")
    return "\n".join(lines) or "(No nodes.)"


def format_todos(todos: list) -> str:
    """Render unresolved lower-level coverage gaps and explain the semantic decisions needed for downward allocation."""
    lines = []
    for todo in todos:
        lines.append(f"TODO: {todo['requirement']} is not covered by the union of its {todo['coverage']}.")
        lines.append("  Uncovered READ : " + (", ".join(todo["read"]) or "(empty)"))
        lines.append("  Uncovered WRITE: " + (", ".join(todo["write"]) or "(empty)"))
    if lines:
        lines.append("Decide which lower node needs the fields, whether a behavior is missing, or whether the upper inference is excessive.")
    return "\n".join(lines) or "Coverage passes for the decompositions checked at this node."


def format_apis(apis: dict) -> str:
    """Render API descriptions and their obligations for existing/retrieved API panels."""
    return "\n\n".join(
        f"{aid} — {api['description']}\n" + format_obligations({aid: api})
        for aid, api in apis.items()
    ) or "(No existing Backend API Primitives.)"
