"""Preserve validation data lifecycles and bind canonical fields without guessing."""

import json
import hashlib
import uuid

from infrastructure.utils.files import read_artifact, save_json, save_text

DATA_INSTRUCTIONS = '''
validation_data is the canonical external data contract. SEED records exist before
scenario execution; CREATED records MUST be created by the associated When/API calls;
DERIVED records MUST result from business processing. Never preload CREATED/DERIVED
records or replace them with screenshot rows. Given prerequisites may use separate,
scenario-local fixtures, without stealing the identities/unique keys of CREATED data.
Capture created IDs from real responses or scoped unique-key queries. Use source record
IDs as symbolic references, not invented persisted business keys. Compare expected fields
after the relevant action, including exact decimal strings. An unbound source field or
entity requires semantic resolution against ER, requirement prose and actual DDL.
Preserve source evidence and document the resolution; do not reject label differences
or silently omit records. Seed SQL is implemented after table creation SQL.
Persisted field values have one shared meaning across requirements. Preserve exact
source codes and literals (including their language) in seed data, isolated Given
fixtures, API writes, selectors and filters. Do not silently translate a stored status
or category in one API while another API persists the source literal. Human-readable
English descriptions are not new storage codes. Fixture identifiers may be separate,
but fixture business values must obey the same source-backed field contract.
'''


def compile_data(raw, schema):
    records, diagnostics = {}, []
    entities = schema["entities"]
    rows = raw.get("data", [])
    if not isinstance(rows, list):
        raise ValueError("Root data must be a list of validation records")
    for row in rows:
        rid, entity, lifecycle = row["id"], row["entity"], row["lifecycle"]
        if rid in records or lifecycle not in {"SEED", "CREATED", "DERIVED"}:
            raise ValueError(f"Invalid/duplicate validation record {rid}")
        record = {**row, "fields": {}, "references": {}, "issues": [], "locator": {}}
        if entity == "test account":
            record.update(status="identity_bootstrap", identity_strategy="trusted_username_and_role_bindings")
            records[rid] = record
            continue
        if entity not in entities:
            record["issues"].append(f"Unknown canonical entity: {entity}")
        else:
            fields = entities[entity]["fields"]
            for key, value in row.get("properties", {}).items():
                if key not in fields:
                    record["issues"].append(f"Unbound property: {key}")
                elif isinstance(value, dict) and "$ref" in value:
                    if not fields[key].get("references"):
                        record["issues"].append(f"{key}: record reference requires a schema FK")
                    record["references"][key] = value["$ref"]
                else:
                    if value is None and not fields[key]["nullable"]:
                        record["issues"].append(f"Required field cannot be null: {key}")
                    record["fields"][key] = value
            primary = [key for key, value in fields.items() if value["primary_key"]]
            if len(primary) != 1:
                record["issues"].append("Data binding requires one primary key")
            else:
                key = primary[0]
                if lifecycle == "SEED" and key not in record["fields"]:
                    if fields[key]["type"] in {"uuid", "string"}:
                        record["fields"][key] = str(uuid.uuid5(uuid.NAMESPACE_URL, "arc-validation:" + rid))
                    else:
                        record["issues"].append(f"SEED needs explicit primary key {key}")
                for name, definition in fields.items():
                    if definition.get("unique") and name in record["fields"] and record["fields"][name] is not None:
                        record["locator"] = {name: record["fields"][name]}
                        break
                if key in record["fields"]:
                    record["locator"] = {key: record["fields"][key]}
            if lifecycle == "SEED":
                for key, field in fields.items():
                    if not field["nullable"] and key not in record["fields"] and key not in record["references"]:
                        record["issues"].append(f"Required SEED field missing: {key}")
        record["status"] = "unresolved" if record["issues"] else "bound"
        record["identity_strategy"] = "seed_primary_key" if lifecycle == "SEED" else "capture_response_or_scoped_locator"
        if record["issues"]:
            diagnostics.append({"record": rid, "lifecycle": lifecycle, "issues": record["issues"]})
        records[rid] = record
    for rid, record in records.items():
        for key, target in record["references"].items():
            if target not in records:
                raise ValueError(f"{rid}.{key}: unknown data reference {target}")
            reference = schema["entities"][record["entity"]]["fields"][key].get("references")
            target_entity = reference.split(".")[0] if reference else None
            if target_entity != records[target]["entity"] and not (target_entity == "users" and records[target]["entity"] == "test account"):
                record["issues"].append(f"{key}: resolve reference entity from source evidence")
                record["status"] = "unresolved"
            if record["lifecycle"] == "SEED" and records[target]["lifecycle"] != "SEED":
                raise ValueError(f"SEED {rid} cannot reference a later-created record")
    requirements = {}
    def visit(node):
        refs = node.get("data", {}).get("requires", []) if isinstance(node.get("data"), dict) else []
        if not set(refs) <= set(records):
            raise ValueError(f"{node['id']}: unknown data.requires")
        requirements[node["id"]] = list(dict.fromkeys([*refs,*[key for key,row in records.items()
            if node['id'] in row.get('requirements',[])]]))
        for child in node.get("children", []) or []:
            visit(child)
    visit(raw)
    fingerprint = lambda value: hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {"records": records, "requirements": requirements, "diagnostics": diagnostics,
        "source_sha256":fingerprint(raw),"schema_sha256":fingerprint(schema["entities"])}


def data_context(catalog, rid):
    selected = set(catalog.get("requirements", {}).get(rid, []))
    pending = list(selected)
    while pending:
        for target in catalog["records"][pending.pop()]["references"].values():
            if target not in selected:
                selected.add(target); pending.append(target)
    records = {}
    for key in sorted(selected):
        row = dict(catalog["records"][key])
        if row["entity"] == "test account":
            # Text contexts carry account names/roles, not duplicate credentials.
            row["properties"] = {k:v for k,v in row["properties"].items() if k != "password"}
        records[key] = row
    return {"records": records, "lifecycle_contract": DATA_INSTRUCTIONS}


def load_data(arc_dir):
    path = arc_dir / "data_bindings.json"
    raw = read_artifact(arc_dir,'requirements.json')
    current = compile_data(raw, read_artifact(arc_dir, "db_schema.json"))
    if path.is_file():
        existing = read_artifact(arc_dir,path.name)
        if all(existing.get(k)==current[k] for k in ("source_sha256","schema_sha256")):
            return existing
    save_json(path,current)
    return current


def publish_seed_data(output, schema, catalog):
    """Publish source evidence; actual INSERT SQL belongs to the seed agent."""
    # Old initialized workspaces may still import this hook. Never run their obsolete
    # static INSERTs alongside the new per-table SQL implementation.
    path = output / "backend/src/db/bound-data.ts"
    if path.exists():
        save_text(path, 'import type Database from "better-sqlite3";\n'
            'export function seedBoundData(_db: Database.Database): void {}\n')
    save_json(output / ".arc/data_bindings.json", catalog)


def startup_assertions(catalog):
    """Verify source SEED values and absence of known future-created identities."""
    result = []
    for rid, row in catalog.get("records",{}).items():
        if row["entity"] == "test account" or row["status"] != "bound" or not row["locator"]:
            continue
        fields = row["fields"] if row["lifecycle"] == "SEED" else {}
        fields = {k:(int(v) if isinstance(v,bool) else json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v) for k,v in fields.items()}
        result.append({"id":rid,"entity":row["entity"],"locator":row["locator"],"lifecycle":row["lifecycle"],"fields":fields})
    return result
