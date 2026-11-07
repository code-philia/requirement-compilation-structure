"""Compile the clone-bundle Mermaid ER dialect into canonical database design.

This module has no workspace-package dependency, so the standalone compiler and
pipeline adapter use the same import/lowering rules. No model discovers ER fields.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from infrastructure.stages.requirements.images import input_file, requirement_nodes
from infrastructure.stages.requirements.tree import RequirementTree

ENTITY = re.compile(r"([A-Za-z][A-Za-z0-9_]*)\s*\{")
ATTRIBUTE = re.compile(r'(\w+)\s+([A-Za-z][A-Za-z0-9_]*)((?:\s+(?:PK|UK))*)\s+"([^"]*)"')
RELATIONSHIP = re.compile(r'([A-Za-z][A-Za-z0-9_]*)\s+(\S{2})--(\S{2})\s+([A-Za-z][A-Za-z0-9_]*)\s*:\s*"([^"]*)"')
REL_ID = re.compile(r"%%\s*relationship_id:\s*(rel_[a-z0-9_]+)")
ER_REFERENCE = re.compile(r"([^#]+\.mmd)#([A-Za-z][A-Za-z0-9_]*)(?: \(([a-z, ]+)\))?")
LEFT = {"||": "1", "o|": "0..1", "}|": "1..*", "}o": "0..*"}
RIGHT = {"||": "1", "|o": "0..1", "|{": "1..*", "o{": "0..*"}
TYPES = {
    "string": ("string", "TEXT"), "text": ("string", "TEXT"),
    "integer": ("integer", "INTEGER"), "decimal": ("string", "TEXT"),
    "float": ("number", "REAL"), "boolean": ("boolean", "INTEGER"),
    "date": ("date", "TEXT"), "datetime": ("datetime", "TEXT"),
    "uuid": ("uuid", "TEXT"), "json": ("json", "TEXT"),
    "file": ("string", "TEXT"), "user_ref": ("uuid", "TEXT"), "unit_ref": ("uuid", "TEXT"),
}


def field(kind, description, *, nullable=True, primary_key=False, unique=False, references=None):
    if kind not in TYPES:
        raise ValueError(f"Unsupported ER logical type: {kind}")
    logical, sqlite = TYPES[kind]
    constraints = []
    if kind == "decimal":
        constraints.append("Exact decimal encoded as text; use decimal-safe application arithmetic, not JS floating point or SQLite REAL/SUM casts. Precision/scale are unspecified by ER.")
    if kind == "file":
        constraints.append("Store a file reference; upload/storage behavior is not defined by this ER attribute.")
    if kind == "uuid" and primary_key:
        constraints.append("Application-generated UUID; no database default was supplied by the ER.")
    return {"description": description, "type": logical, "source_type": kind, "sqlite_type": sqlite,
        "nullable": nullable, "primary_key": primary_key, "unique": unique,
        "references": references, "constraints": constraints}


def parse_er(text):
    entities, relations = {}, {}
    current, pending = None, None
    lines = [(number, line.strip()) for number, line in enumerate(text.splitlines(), 1) if line.strip()]
    if not lines or lines[0][1] != "erDiagram":
        raise ValueError("ER source must start with erDiagram")
    for number, line in lines[1:]:
        if current is not None:
            if line == "}":
                current = None
                continue
            match = ATTRIBUTE.fullmatch(line)
            if not match:
                raise ValueError(f"ER line {number}: unsupported attribute: {line}")
            kind, name, qualifiers, label = match.groups()
            if name in entities[current]["fields"]:
                raise ValueError(f"ER line {number}: duplicate attribute {current}.{name}")
            required = label.endswith(" (required)")
            primary = "PK" in qualifiers.split()
            entities[current]["fields"][name] = field(kind, label.removesuffix(" (required)"),
                nullable=not (required or primary), primary_key=primary, unique="UK" in qualifiers.split())
            continue
        if match := REL_ID.fullmatch(line):
            if pending is not None:
                raise ValueError(f"ER relationship {pending} has no definition")
            pending = match[1]
        elif match := RELATIONSHIP.fullmatch(line):
            source, left, right, target, label = match.groups()
            if not pending or pending in relations or left not in LEFT or right not in RIGHT:
                raise ValueError(f"ER line {number}: missing/duplicate relationship ID or invalid cardinality")
            relations[pending] = {"id": pending, "description": label, "source": source, "target": target,
                "source_cardinality": LEFT[left], "target_cardinality": RIGHT[right]}
            pending = None
        elif pending is not None:
            raise ValueError(f"ER relationship {pending} has no definition")
        elif match := ENTITY.fullmatch(line):
            current = match[1]
            if current in entities:
                raise ValueError(f"Duplicate ER entity: {current}")
            entities[current] = {"description": current, "fields": {}, "origin": "er"}
        elif not line.startswith("%%"):
            raise ValueError(f"ER line {number}: unsupported syntax: {line}")
    if current is not None or pending is not None:
        raise ValueError("Unterminated ER entity or relationship declaration")
    if not entities:
        raise ValueError("ER model contains no entities")
    for relationship in relations.values():
        for target in (relationship["source"], relationship["target"]):
            if target not in entities:
                raise ValueError(f"{relationship['id']} references unknown ER entity {target}")
    return entities, relations


def entity_key(entities, name):
    keys = [key for key, value in entities[name]["fields"].items() if value["primary_key"]]
    if len(keys) != 1:
        raise ValueError(f"Relationship target {name} requires one primary-key field; composite-key references require an explicit mapping")
    return keys[0]


def add_foreign_key(entities, holder, name, target, *, nullable, unique=False, description=""):
    if name in entities[holder]["fields"]:
        raise ValueError(f"Generated ER foreign key collides with {holder}.{name}; publish an explicit unambiguous ER mapping")
    key = entity_key(entities, target)
    target_field = entities[target]["fields"][key]
    record = {**target_field, "description": description, "nullable": nullable,
        "primary_key": False, "unique": unique, "references": f"{target}.{key}", "constraints": []}
    entities[holder]["fields"][name] = record
    return f"{holder}.{name}"


def fingerprint(entities):
    return hashlib.sha256(json.dumps(entities, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def import_er_schema(requirements, input_dir):
    """Return None only for legacy inputs without ER; declared broken ER never falls back."""
    input_dir = Path(input_dir).resolve()
    nodes = list(requirement_nodes(requirements))
    citations = {}
    paths = set()
    for node in nodes:
        description = node.get("description", {})
        refs = description.get("er", []) if isinstance(description, dict) else []
        if not isinstance(refs, list):
            raise ValueError(f"{node['id']}: description.er must be a list")
        citations[node["id"]] = []
        for reference in refs:
            match = ER_REFERENCE.fullmatch(reference) if isinstance(reference, str) else None
            if not match:
                raise ValueError(f"{node['id']}: invalid ER reference: {reference}")
            path, fragment, operations = match.groups()
            if operations and not set(operations.split(", ")) <= {"create", "read", "update", "delete"}:
                raise ValueError(f"Invalid ER CRUD annotation: {reference}")
            paths.add(path)
            citations[node["id"]].append(fragment)
    if not paths:
        conventional = input_dir / "reference/er/model.mmd"
        if not conventional.exists():
            return None
        paths.add("reference/er/model.mmd")
    if len(paths) != 1:
        raise ValueError("One canonical ER model is required; multiple Mermaid sources need an explicit merge")
    source = input_file(input_dir, next(iter(paths)))
    source_bytes = source.read_bytes()
    entities, relationships = parse_er(source_bytes.decode("utf-8-sig"))
    source_entities = list(entities)
    generated, diagnostics = [], []
    source_attribute_count = sum(len(entity["fields"]) for entity in entities.values())
    for name, entity in entities.items():
        if not any(value["primary_key"] for value in entity["fields"].values()):
            if "id" in entity["fields"]:
                raise ValueError(f"ER entity {name} has a non-primary id field; declare its intended key explicitly")
            entity["fields"] = {"id": field("uuid", "Technical UUID primary key", nullable=False, primary_key=True), **entity["fields"]}
            generated.append({"field": f"{name}.id", "reason": "ER defines no primary key"})
    # user_ref/unit_ref point outside the business ER. Supply storage targets only;
    # this does not implement login, sessions, authorization or tenant isolation.
    external_refs = [(name, key, value["source_type"]) for name, entity in entities.items()
        for key, value in entity["fields"].items() if value["source_type"] in {"user_ref", "unit_ref"}]
    for owner, key, kind in external_refs:
        target = "users" if kind == "user_ref" else "org_units"
        if target not in entities:
            fields = {"id": field("uuid", "Referenced identity UUID", nullable=False, primary_key=True)}
            if kind == "user_ref":
                fields.update(username=field("string", "Account name", nullable=False, unique=True),
                    password_hash=field("string", "Password hash; never plaintext", nullable=False))
            else:
                fields["name"] = field("string", "Organization unit name", nullable=False)
            entities[target] = {"description": "Auxiliary identity storage for ER references", "fields": fields, "origin": "reference_target"}
            generated.append({"table": target, "reason": kind + " storage target; authentication/authorization deferred"})
        pk = entity_key(entities, target)
        if entities[target]["fields"][pk]["type"] != "uuid":
            raise ValueError(f"{kind} target {target}.{pk} must have UUID type")
        entities[owner]["fields"][key]["references"] = f"{target}.{pk}"
    plans = []
    for relation in relationships.values():
        source_name, target = relation["source"], relation["target"]
        smany, tmany = relation["source_cardinality"].endswith("*"), relation["target_cardinality"].endswith("*")
        if smany and tmany:
            plans.append((relation, None, None))
        elif tmany:
            plans.append((relation, target, source_name))
        else:
            plans.append((relation, source_name, target))
    pairs = Counter((holder, target) for _, holder, target in plans if holder)
    mapping = {}
    for relation, holder, target in plans:
        rid = relation["id"]
        source_name, target_name = relation["source"], relation["target"]
        if holder is None:
            if rid in entities:
                raise ValueError(f"ER association table name collides with entity {rid}")
            entities[rid] = {"description": relation["description"], "origin": "er_relationship",
                "fields": {"id": field("uuid", "Association UUID", nullable=False, primary_key=True)}}
            source_column = source_name + "_id" if source_name != target_name else "source_id"
            target_column = target_name + "_id" if source_name != target_name else "target_id"
            columns = [add_foreign_key(entities, rid, source_column, source_name, nullable=False, description=relation["description"]),
                add_foreign_key(entities, rid, target_column, target_name, nullable=False, description=relation["description"])]
            entities[rid]["unique_constraints"] = [[source_column, target_column]]
            mapping[rid] = {**relation, "table": rid, "fields": columns, "kind": "association"}
            generated.append({"table": rid, "reason": rid + " many-to-many relationship"})
        else:
            suffix = rid.removeprefix("rel_")
            if suffix.startswith(holder + "_"):
                column = suffix.removeprefix(holder + "_") + "_id"
            else:
                column = target + "_id" if pairs[holder, target] == 1 else suffix + "_id"
            target_cardinality = relation["source_cardinality"] if relation["target_cardinality"].endswith("*") else relation["target_cardinality"]
            nullable = target_cardinality == "0..1"
            one_to_one = not relation["source_cardinality"].endswith("*") and not relation["target_cardinality"].endswith("*")
            symbol = add_foreign_key(entities, holder, column, target, nullable=nullable,
                unique=one_to_one, description=relation["description"])
            mapping[rid] = {**relation, "table": holder, "fields": [symbol], "kind": "foreign_key"}
            generated.append({"field": symbol, "reason": rid, "references": entities[holder]["fields"][column]["references"]})
        if "1..*" in (relation["source_cardinality"], relation["target_cardinality"]) or (
                relation["source_cardinality"] == relation["target_cardinality"] == "1"):
            diagnostics.append({"code": "ER_CARDINALITY_APPLICATION_RULE", "relationship": rid,
                "message": "Minimum related-row existence beyond the stored FK requires application-level enforcement."})
    decimal_count = sum(value["source_type"] == "decimal" for entity in entities.values() for value in entity["fields"].values())
    if decimal_count:
        diagnostics.append({"code": "ER_DECIMAL_TEXT_STORAGE", "count": decimal_count,
            "message": "Decimal precision/scale are unspecified. Store exact decimal text; decimal-safe arithmetic/aggregation must be implemented by backend."})
    tree = RequirementTree(requirements)
    parents = {child["id"]: node["id"] for node in nodes for child in node.get("children", []) or []}
    allocations, allocation_sources = {}, {}
    for rid in tree.requirements:
        if tree.children[rid]:
            allocations[rid] = []
            continue
        fragments, current = [], rid
        while current:
            fragments.extend(citations[current])
            current = parents.get(current)
        selected = set()
        for fragment in fragments:
            if fragment in source_entities:
                selected.add(fragment)
            elif fragment in mapping:
                selected.update((mapping[fragment]["source"], mapping[fragment]["target"], mapping[fragment]["table"]))
            else:
                raise ValueError(f"{rid}: unresolved ER fragment {fragment}")
        allocation_sources[rid] = "explicit_or_ancestor_er" if selected else "all_fields_without_er_citation"
        if not selected:
            selected = set(entities)
        else:
            direct = set(selected)
            for relation in mapping.values():
                if {relation["source"], relation["target"]} & direct:
                    selected.update((relation["source"], relation["target"], relation["table"]))
            pending = list(selected)
            while pending:
                for value in entities[pending.pop()]["fields"].values():
                    if value["references"]:
                        target = value["references"].split(".")[0]
                        if target not in selected:
                            selected.add(target)
                            pending.append(target)
        allocations[rid] = sorted(f"{name}.{key}" for name in selected for key in entities[name]["fields"])
    return {"entities": entities, "requirements": allocations, "er_import": {
        "source_path": source.relative_to(input_dir).as_posix(),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_entities": source_entities, "source_attribute_count": source_attribute_count,
        "relationships": mapping, "generated": generated, "diagnostics": diagnostics,
        "requirement_associations": allocation_sources, "schema_sha256": fingerprint(entities)}}



def validate_imported_schema(arc_dir, schema):
    """Check that the model implements the current imported design and ER source."""
    imported = schema["er_import"]
    if fingerprint(schema["entities"]) != imported["schema_sha256"]:
        raise ValueError("Imported ER schema was changed; update the ER source and rerun stage 02")
    source = input_file(arc_dir.parent, imported["source_path"])
    if hashlib.sha256(source.read_bytes()).hexdigest() != imported["source_sha256"]:
        raise ValueError("ER source changed after schema import; rerun stage 02")
