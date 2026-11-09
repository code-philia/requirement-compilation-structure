"""Resolve the requirement tree, database symbols, and requirement obligations."""

from pathlib import Path
from infrastructure.stages.backend.evidence import load_evidence, scoped_evidence

from infrastructure.utils.files import read_artifact

from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.requirements.data import load_data, data_context


def load_context(arc_dir: Path):
    """Load original evidence and implemented schema, without an API contract artifact."""
    tree = RequirementTree(read_artifact(arc_dir, "requirements.json"))
    tree.backend_evidence = load_evidence(arc_dir)
    tree.validation_data = load_data(arc_dir)
    findings_path = arc_dir / "acceptance_findings.json"
    tree.acceptance_findings = []
    if findings_path.is_file():
        findings = read_artifact(arc_dir, findings_path.name)
        if findings.get("source_sha256") != tree.validation_data["source_sha256"]:
            raise ValueError("Independent acceptance findings belong to another source; review before reusing")
        for item in findings.get("items", []):
            if not item.get("requirements") or not set(item["requirements"]) <= set(tree.requirements) or not item.get("source_refs"):
                raise ValueError("Independent acceptance findings need known requirements and source references")
            if item.get("status") == "OPEN":tree.acceptance_findings.append(item)
    foundation_path = arc_dir / "backend_foundation.json"
    tree.backend_foundation = read_artifact(arc_dir, foundation_path.name) if foundation_path.is_file() else {"enabled":False}
    schema = read_artifact(arc_dir, "db_schema.json")
    from infrastructure.stages.database.seeds import MANIFEST, seed_assertions
    seed_path = arc_dir.parent / MANIFEST
    if seed_path.is_file():
        seed_assertions(arc_dir.parent, schema, tree.validation_data)
        import json
        resolutions = json.loads(seed_path.read_text(encoding="utf-8-sig"))["records"]
        for key, resolution in resolutions.items():
            tree.validation_data["records"][key]["seed_resolution"] = resolution
    return tree, schema



def requirement_context(tree, rid: str) -> dict:
    """Return one requirement with its own structured steps and their concatenated teaching/model context."""
    return {**tree.requirements[rid], "steps": [tree.steps[sid] for sid in tree.own_steps[rid]],
        "validation_data": data_context(getattr(tree,"validation_data",{}),rid),
        "independent_acceptance_findings": [item for item in getattr(tree,"acceptance_findings",[]) if rid in item["requirements"]],
        "backend_evidence": scoped_evidence(getattr(tree,"backend_evidence",{}),rid),
        "backend_foundation": getattr(tree,"backend_foundation",{"enabled":False})}


def api_requirement_uses(tree, allocations: dict, aid: str) -> list[dict]:
    """Supply every API owner once, with structured steps as the sole scenario representation."""
    return [requirement_context(tree,rid) for rid, ids in allocations.items() if aid in ids]


def supplied_sources(output: Path, api: dict, schema: dict) -> list[str]:
    """Supply known database and fixture paths alongside the backend directory scope."""
    entities = {symbol.split(".")[0] for mode in ("read", "write") for symbol in api[mode]}
    pending = list(entities)
    while pending:
        name = pending.pop()
        for field in schema["entities"][name]["fields"].values():
            if field["references"]:
                target = field["references"].split(".")[0]
                if target not in entities:
                    entities.add(target)
                    pending.append(target)
    paths = ["backend/src/api/types.ts", "backend/src/db/client.ts", "backend/tests/support/context.ts"]
    paths.extend(f"backend/src/db/tables/{name}.sql" for name in sorted(entities))
    paths.extend(f"backend/src/db/seeds/{name}.sql" for name in sorted(entities)
        if (output / f"backend/src/db/seeds/{name}.sql").is_file())
    if (output / "backend/src/platform/runtime.ts").is_file():
        paths += ["backend/src/platform/runtime.ts", "backend/src/platform/types.ts", "backend/src/platform/settings.ts"]
    return paths


def related_schema(schema, records):
    """Project explicitly used entities; keep their complete definitions for SQL fixtures."""
    records = list(records)
    if not records or any('read' not in record and 'write' not in record for record in records):
        return schema['entities']
    names = {field.split(".")[0] for record in records for mode in ("read", "write")
        for field in record.get(mode, [])}
    return {name: value for name, value in schema["entities"].items() if name in names}


def requirement_schema(schema, rid):
    """Source-linked tables and FK parents, without unrelated system table definitions."""
    names = {symbol.split('.', 1)[0] for symbol in schema.get('requirements', {}).get(rid, [])}
    pending = list(names)
    while pending:
        for field in schema['entities'].get(pending.pop(), {}).get('fields', {}).values():
            reference = field.get('references')
            if reference:
                target = reference.split('.', 1)[0]
                if target not in names:
                    names.add(target)
                    pending.append(target)
    return {name: entity for name, entity in schema['entities'].items() if name in names}
