"""Design the initial logical schema from complete ER content in one native loop."""

import hashlib
import json
from pathlib import Path

from infrastructure.shared.project.git import checkpoint
from infrastructure.stages.database.design_agent import DatabaseDesignAgent, schema_issues
from infrastructure.stages.requirements.images import input_file
from infrastructure.utils.files import read_artifact, save_json
from infrastructure.utils.presentation.console import DemoConsole


def er_sources(input_dir):
    """Locate source files without interpreting Mermaid semantics."""
    root = Path(input_dir).resolve()
    conventional = [root / "reference/er/model.mmd", root / "er/model.mmd", root / "model.mmd"]
    paths = [path for path in conventional if path.is_file()]
    if not paths:
        paths = sorted(root.rglob("*.mmd"))
    if not paths:
        raise ValueError("Database design needs er/model.mmd or reference/er/model.mmd")
    return {path.relative_to(root).as_posix(): input_file(root, path.relative_to(root).as_posix()).read_text(encoding="utf-8-sig")
        for path in paths}


def source_fingerprint(sources):
    return hashlib.sha256(json.dumps(sources, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def build_er_schema(input_dir, arc_dir, pause=False, max_turns=40):
    """One agent reads original ER and incrementally creates logical definitions."""
    sources = er_sources(input_dir)
    raw = read_artifact(arc_dir,'requirements.json')
    from infrastructure.stages.backend.evidence import compile_evidence
    evidence = compile_evidence(raw,input_dir)
    nodes = []
    def visit(node, parent=None):
        nodes.append({key:value for key,value in node.items() if key!='children' and not (key=='data' and isinstance(value,list))} | {'parent':parent})
        for child in node.get('children',[]) or []:
            visit(child,node['id'])
    visit(raw)
    design_input = {'requirements':nodes,'source_data':raw.get('data',[]),
        'authorization':evidence.get('authorization',{}),'processes':evidence.get('processes',{})}
    startup_signature = source_fingerprint({'version':'global_requirements_v1','evidence':design_input})
    previous_path = arc_dir / "db_schema.json"
    previous = read_artifact(arc_dir, previous_path.name) if previous_path.is_file() else {}
    reusable = (previous.get("er_design", {}).get("source_sha256") == source_fingerprint(sources)
        and previous.get("er_design", {}).get("identity_model") == "source_driven"
        and previous.get('er_design',{}).get('startup_sha256')==startup_signature
        and set(previous.get('requirement_support',{}))=={node['id'] for node in nodes})
    schema = {"entities": {}, "requirements": {}, "decisions": [],
        "er_design": {"mode": "agent", "identity_model": "source_driven", "source_sha256": source_fingerprint(sources),
            "sources": list(sources), "startup_sha256":startup_signature,"status": "BUILDING"}}
    if reusable:
        schema = previous
    save_json(arc_dir / "backend_evidence.json", evidence)
    save_json(arc_dir / "db_schema.json", schema)
    console = DemoConsole(pause)
    if reusable and schema["er_design"].get("status") == "GREEN" and not schema_issues(schema):
        save_json(arc_dir/'db_requirement_support.json',schema['requirement_support'])
        console.show("ER schema | Reuse", "ER evidence is unchanged; reuse the accepted logical schema and requirement-driven repairs.")
        return schema
    console.show("Database | Global logical design", f"Read complete ER, {len(nodes)} requirement points and root data together before SQL; no per-requirement correction pass.")
    agent = DatabaseDesignAgent(schema, sources, persist=lambda: save_json(arc_dir / "db_schema.json", schema))
    result = agent.run({"task": "Design the COMPLETE database once using ER, EVERY supplied requirement, source startup facts and authorization/process evidence, before any SQL implementation.",
        **design_input,
        'policy': 'ER is the starting point, not the only evidence. Identify all required persistence now, including identity, tenancy, state transitions, numbering and audit only where source requires them. '
            'For tenant-scoped resources model a persisted ownership column or unambiguous FK path; do not leave ownership to later handler guesses. '
            'No preset business tables. Explain every requirement in requirement_support, using entities=[] for genuine UI-only behavior. '
            'Finish schema before writing SQL; there is no later per-requirement database correction stage.'}, max_turns=max_turns)
    save_json(arc_dir/'db_requirement_support.json',schema['requirement_support'])
    schema["er_design"].update(status="GREEN", summary=result["summary"])
    save_json(arc_dir / "db_schema.json", schema)
    checkpoint(arc_dir.parent, task="ER schema", action="Publish agent-designed logical schema", status="GREEN",
        details={"sources": list(sources), "entities": list(schema["entities"])})
    return schema
