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
from infrastructure.stages.database.startup import startup_context, model_seed_context, effective_requirements, explicit_records, digest, PLAN, DatabaseBatchAgent, analysis_batches, VERSION as STARTUP_VERSION


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
    startup_signature = source_fingerprint({'source_data':startup_context(raw),
        'authorization':evidence.get('authorization',{}).get('catalog',{}),'startup_version':STARTUP_VERSION})
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
        'source_data':model_seed_context(startup_context(raw)),
        "source_authorization_catalog": evidence.get("authorization", {}).get("catalog", {}) if evidence.get("authorization") else {}}, max_turns=max_turns)
    schema["er_design"].update(status="GREEN", summary=result["summary"])
    save_json(arc_dir / "db_schema.json", schema)
    checkpoint(arc_dir.parent, task="ER schema", action="Publish agent-designed logical schema", status="GREEN",
        details={"sources": list(sources), "entities": list(schema["entities"])})
    return schema


def refine_database(input_dir, arc_dir, pause=False, max_turns=16):
    """One batched leaf pass publishes schema repairs, startup facts and obligations."""
    sources = er_sources(input_dir)
    schema = read_artifact(arc_dir, "db_schema.json")
    if schema.get("er_design", {}).get("identity_model") != "source_driven":
        raise ValueError("Rerun build_db_schema to replace the legacy preset identity schema with source-driven design")
    if schema.get("er_design", {}).get("source_sha256") != source_fingerprint(sources):
        raise ValueError("ER source changed; rerun build_db_schema before requirement analysis")
    raw = read_artifact(arc_dir, "requirements.json")
    tree = RequirementTree(raw)
    signature = source_fingerprint({"requirements": raw, "er": sources, "identity_model": "source_driven",'startup_version':STARTUP_VERSION})
    progress_path, obligations_path = arc_dir / "db_analysis.json", arc_dir / "db_obligations.json"
    previous = read_artifact(arc_dir, progress_path.name) if progress_path.is_file() else {}
    reusable = previous.get("source_sha256") == signature and previous.get("schema_sha256") == source_fingerprint(schema["entities"])
    obligations = read_artifact(arc_dir, obligations_path.name) if reusable and obligations_path.is_file() else {"requirements": {}, "steps": {}}
    progress = previous if reusable else {"requirements": {}}
    progress.update(status="RUNNING", source_sha256=signature)
    console = DemoConsole(pause)
    failures = TaskFailures(arc_dir, "analyze_db_requirements", console)
    model, retriever = TextModel(json_mode=False), SchemaRetriever()
    evidence = read_artifact(arc_dir,'backend_evidence.json') if (arc_dir/'backend_evidence.json').is_file() else {}
    catalog = evidence.get('authorization',{}).get('catalog',{})
    prior_plan = read_artifact(arc_dir,PLAN) if (arc_dir/PLAN).is_file() else {}
    plan_reusable = (prior_plan.get('version')==STARTUP_VERSION
        and prior_plan.get('source_sha256')==digest(raw)
        and prior_plan.get('authorization_sha256')==digest(catalog))
    startup = prior_plan if plan_reusable else {'version':STARTUP_VERSION,
        'source_sha256':digest(raw),'authorization_sha256':digest(catalog),
        'explicit_records':explicit_records(raw),'derived_records':{},'requirements':{},'batches':{}}
    startup['status'] = 'RUNNING'

    def publish():
        progress["schema_sha256"] = source_fingerprint(schema["entities"])
        save_json(arc_dir / "db_schema.json", schema)
        save_json(arc_dir / "db_obligations.json", obligations)
        save_json(arc_dir / "db_analysis.json", progress)
        startup["schema_sha256"] = digest(schema["entities"])
        save_json(arc_dir / PLAN, startup)

    publish()
    pending = {rid for rid in tree.leaves if not (
        progress['requirements'].get(rid,{}).get('status')=='GREEN'
        and rid in obligations['requirements'] and rid in startup['requirements']
        and all(sid in obligations['steps'] for sid in tree.own_steps[rid]))}
    for rid in set(tree.leaves)-pending:
        failures.report['tasks'][rid] = {'status':'GREEN'}
    batches = list(analysis_batches(tree,pending))
    for index,batch in enumerate(batches,1):
        ids = [node['id'] for node in batch]
        task_id = 'batch-'+digest(ids)[:12]
        for rid in ids:
            progress['requirements'][rid] = {'status':'RUNNING'}
        with failures.task(task_id):
            console.show(f'Database analysis | Batch {index}/{len(batches)}',
                'Repair schema, collect source-required presets and derive effects together: '+', '.join(ids))
            query = json.dumps(batch,ensure_ascii=False)
            candidates = retriever.retrieve(query,schema,top_k=16)['entities']
            agent = DatabaseBatchAgent(schema,{},startup,raw,model=model,persist=publish)
            inferred = agent.run({'requirements':batch,
                'source_data':model_seed_context(startup['explicit_records']),
                'known_presets':model_seed_context(startup['derived_records']),
                'source_authorization_catalog':catalog,'provided_entities':candidates},
                max_turns=max(24,max_turns))
            for rid,result in inferred['obligations'].items():
                obligations['requirements'][rid] = result['requirement']
                obligations['steps'].update(result['steps'])
                schema['requirements'][rid] = sorted({field for mode in ('read','write','observation_read')
                    for field in result['requirement'].get(mode,[])})
                progress['requirements'][rid] = {'status':'GREEN'}
            startup['batches'][task_id] = {'status':'GREEN','requirements':ids,'summary':inferred['summary']}
            publish()
            checkpoint(arc_dir.parent,task=task_id,
                action='Publish schema, startup evidence and obligations',status='GREEN')
        if failures.report['tasks'][task_id]['status']=='FAILED':
            for rid in ids:
                progress['requirements'][rid] = failures.report['tasks'][task_id]
        publish()
    progress["status"] = "COMPLETED_WITH_FAILURES" if any(
        item["status"] == "FAILED" for item in progress["requirements"].values()) else "GREEN"
    startup["status"] = progress["status"]
    publish()
    from infrastructure.stages.requirements.data import compile_data
    save_json(arc_dir / "data_bindings.json", compile_data(effective_requirements(raw,arc_dir), schema))
    publish()
    failures.finish()
    return {"status": "GREEN", "requirements": obligations["requirements"],
        "steps": obligations["steps"], "entities": len(schema["entities"])}
