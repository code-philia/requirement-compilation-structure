"""ER-first design followed by joint schema repair and requirement obligation analysis."""

import hashlib
import json
from pathlib import Path

from infrastructure.shared.models.text import TextModel
from infrastructure.shared.rag.schema import SchemaRetriever
from infrastructure.shared.agent.tasks import TaskFailures
from infrastructure.shared.project.git import checkpoint
from infrastructure.stages.database.design_agent import DatabaseDesignAgent, schema_issues
from infrastructure.stages.requirements.images import input_file
from infrastructure.stages.requirements.tree import RequirementTree
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
    previous_path = arc_dir / "db_schema.json"
    previous = read_artifact(arc_dir, previous_path.name) if previous_path.is_file() else {}
    reusable = (previous.get("er_design", {}).get("source_sha256") == source_fingerprint(sources)
        and previous.get("er_design", {}).get("identity_model") == "source_driven")
    schema = {"entities": {}, "requirements": {}, "decisions": [],
        "er_design": {"mode": "agent", "identity_model": "source_driven", "source_sha256": source_fingerprint(sources),
            "sources": list(sources), "status": "BUILDING"}}
    if reusable:
        schema = previous
    from infrastructure.stages.backend.evidence import compile_evidence
    evidence = compile_evidence(read_artifact(arc_dir, "requirements.json"), input_dir)
    save_json(arc_dir / "backend_evidence.json", evidence)
    save_json(arc_dir / "db_schema.json", schema)
    console = DemoConsole(pause)
    if reusable and schema["er_design"].get("status") == "GREEN" and not schema_issues(schema):
        console.show("ER schema | Reuse", "ER evidence is unchanged; reuse the accepted logical schema and requirement-driven repairs.")
        return schema
    console.show("ER schema | Logical design", "Read ER evidence; create definitions with native tools, without SQL or per-requirement calls.")
    agent = DatabaseDesignAgent(schema, sources, persist=lambda: save_json(arc_dir / "db_schema.json", schema))
    result = agent.run({"task": "Read the complete ER source, resolve conflicts and construct the initial canonical schema. No identity tables or user types are preset.",
        "source_authorization_catalog": evidence.get("authorization", {}).get("catalog", {}) if evidence.get("authorization") else {}}, max_turns=max_turns)
    schema["er_design"].update(status="GREEN", summary=result["summary"])
    save_json(arc_dir / "db_schema.json", schema)
    checkpoint(arc_dir.parent, task="ER schema", action="Publish agent-designed logical schema", status="GREEN",
        details={"sources": list(sources), "entities": list(schema["entities"])})
    return schema


def refine_database(input_dir, arc_dir, pause=False, max_turns=16):
    """Every node gets own effects; schema repairs and obligations are published together."""
    sources = er_sources(input_dir)
    schema = read_artifact(arc_dir, "db_schema.json")
    if schema.get("er_design", {}).get("identity_model") != "source_driven":
        raise ValueError("Rerun 02_build_db_schema to replace the legacy preset identity schema with source-driven design")
    if schema.get("er_design", {}).get("source_sha256") != source_fingerprint(sources):
        raise ValueError("ER source changed; rerun 02_build_db_schema before requirement analysis")
    raw = read_artifact(arc_dir, "requirements.json")
    tree = RequirementTree(raw)
    signature = source_fingerprint({"requirements": raw, "er": sources, "identity_model": "source_driven"})
    progress_path, obligations_path = arc_dir / "db_analysis.json", arc_dir / "db_obligations.json"
    previous = read_artifact(arc_dir, progress_path.name) if progress_path.is_file() else {}
    reusable = previous.get("source_sha256") == signature and previous.get("schema_sha256") == source_fingerprint(schema["entities"])
    obligations = read_artifact(arc_dir, obligations_path.name) if reusable and obligations_path.is_file() else {"requirements": {}, "steps": {}}
    progress = previous if reusable else {"requirements": {}}
    progress.update(status="RUNNING", source_sha256=signature)
    console = DemoConsole(pause)
    failures = TaskFailures(arc_dir, "03_infer_db_obligations", console)
    model, retriever = TextModel(json_mode=False), SchemaRetriever()

    def publish():
        progress["schema_sha256"] = source_fingerprint(schema["entities"])
        save_json(arc_dir / "db_schema.json", schema)
        save_json(arc_dir / "db_obligations.json", obligations)
        save_json(arc_dir / "db_analysis.json", progress)

    publish()
    for index, rid in enumerate(tree.postorder, 1):
        if (progress["requirements"].get(rid, {}).get("status") == "GREEN"
                and rid in obligations["requirements"]
                and all(sid in obligations["steps"] for sid in tree.own_steps[rid])):
            console.show(f"Database analysis | Reuse {rid}", "Unchanged source and retained schema/obligations; skip accepted node.")
            failures.report["tasks"][rid] = {"status": "GREEN"}
            continue
        progress["requirements"][rid] = {"status": "RUNNING"}
        with failures.task(rid):
            console.show(f"Database analysis {index}/{len(tree.postorder)} | {rid}",
                "Derive own requirement/step effects and repair missing logical schema together.")
            node = tree.raw[rid]
            ancestors, parent = [], tree.parents.get(rid)
            while parent:
                ancestors.append({**tree.requirements[parent], "description_evidence": tree.raw[parent].get("description")})
                parent = tree.parents.get(parent)
            query = json.dumps({"requirement": node.get("description"), "scenarios": node.get("scenarios")}, ensure_ascii=False)
            candidates = retriever.retrieve(query, schema, top_k=12)["entities"]
            agent = DatabaseDesignAgent(schema, sources, mode="obligations", model=model, persist=publish)
            inferred = agent.run({"requirement": tree.requirements[rid],
                "description_evidence": node.get("description", {}),
                "steps": [tree.steps[sid] for sid in tree.own_steps[rid]],
                "parent_context": ancestors, "is_organizational_parent": bool(tree.children[rid]),
                "provided_entities": candidates}, max_turns=max_turns)
            obligations["requirements"][rid] = inferred["requirement"]
            obligations["steps"].update(inferred["steps"])
            record = inferred["requirement"]
            schema["requirements"][rid] = sorted(set(record["read"] + record["write"] + record.get("observation_read", [])))
            progress["requirements"][rid] = {"status": "GREEN"}
            publish()
            checkpoint(arc_dir.parent, task=rid, action="Publish schema repairs and database obligations", status="GREEN")
        if failures.report["tasks"][rid]["status"] == "FAILED":
            progress["requirements"][rid] = failures.report["tasks"][rid]
        publish()
    progress["status"] = "COMPLETED_WITH_FAILURES" if any(
        item["status"] == "FAILED" for item in progress["requirements"].values()) else "GREEN"
    from infrastructure.stages.requirements.data import compile_data
    save_json(arc_dir / "data_bindings.json", compile_data(raw, schema))
    publish()
    failures.finish()
    return {"status": "GREEN", "requirements": obligations["requirements"],
        "steps": obligations["steps"], "entities": len(schema["entities"])}
