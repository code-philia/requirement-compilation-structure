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
    startup_signature = 'er_only_v1'
    previous_path = arc_dir / "db_schema.json"
    previous = read_artifact(arc_dir, previous_path.name) if previous_path.is_file() else {}
    reusable = (previous.get("er_design", {}).get("source_sha256") == source_fingerprint(sources)
        and previous.get("er_design", {}).get("identity_model") == "source_driven"
        and previous.get('er_design',{}).get('startup_sha256')==startup_signature)
    schema = {"entities": {}, "requirements": {}, "decisions": [],
        "er_design": {"mode": "agent", "identity_model": "source_driven", "source_sha256": source_fingerprint(sources),
            "sources": list(sources), "startup_sha256":startup_signature,"status": "BUILDING"}}
    if reusable:
        schema = previous
    save_json(arc_dir / "backend_evidence.json", evidence)
    save_json(arc_dir / "db_schema.json", schema)
    console = DemoConsole(pause)
    if reusable and schema["er_design"].get("status") == "GREEN" and not schema_issues(schema):
        console.show("ER schema | Reuse", "ER evidence is unchanged; reuse the accepted logical schema and requirement-driven repairs.")
        return schema
    console.show("ER schema | Logical design", "Read ER evidence; create definitions with native tools, without SQL or per-requirement calls.")
    agent = DatabaseDesignAgent(schema, sources, persist=lambda: save_json(arc_dir / "db_schema.json", schema))
    result = agent.run({"task": "Read the complete ER source, resolve conflicts and construct the initial canonical schema. No identity tables or user types are preset.",
        'policy': 'Use ER only. Data insertion and requirement-driven corrections happen in later implementation loops.'}, max_turns=max_turns)
    schema["er_design"].update(status="GREEN", summary=result["summary"])
    save_json(arc_dir / "db_schema.json", schema)
    checkpoint(arc_dir.parent, task="ER schema", action="Publish agent-designed logical schema", status="GREEN",
        details={"sources": list(sources), "entities": list(schema["entities"])})
    return schema
