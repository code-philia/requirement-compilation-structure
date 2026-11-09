"""Auditable upstream revision requests; application agents cannot edit contracts."""

import json
from uuid import uuid4

from infrastructure.utils.files import save_json

TARGETS = {
    "schema":"02_build_db_schema", "backend_foundation":"02_design_backend_foundation",
    "obligations":"03_infer_db_obligations", "backend_api":"05_design_backend_apis",
    "ui_design":"07_design_ui", "triggers":"09_design_frontend_triggers",
    "acceptance":"10_implement_frontend_tdd", "validation_data":"02_design_backend_foundation",
    "input_evidence":"01_explore_requirement",
    "compiler_runtime":"compiler_maintenance",
}
STAGES = ["01_explore_requirement","02_build_db_schema","02_design_backend_foundation","03_infer_db_obligations",
    "04_implement_db","05_design_backend_apis","06_implement_backend_tdd","07_design_ui",
    "08_implement_ui","09_design_frontend_triggers","10_implement_frontend_tdd"]


class UpstreamRepairRequired(RuntimeError):
    def __init__(self, record):
        self.revision_request = record
        super().__init__(f"Upstream revision required: {record['id']} → {record['target_stage']}: {record['reason']}")


def request_design_revision(files, target, requirements, source_refs, reason, proposed_change, issue_code="other"):
    if target not in TARGETS or not requirements or not source_refs or not reason.strip() or not proposed_change.strip():
        raise ValueError("An upstream revision needs a known target, requirement IDs, evidence and a concrete change")
    if not isinstance(requirements,list) or not isinstance(source_refs,list) or any(not isinstance(x,str) or not x.strip() for x in requirements+source_refs):
        raise ValueError("requirements/source_refs must be nonempty string arrays")
    if issue_code not in {"other","missing_scoped_read"} or (issue_code=="missing_scoped_read" and target!="backend_api"):
        raise ValueError("Invalid upstream revision issue code")
    known = set()
    raw = json.loads((files.output / ".arc/requirements.json").read_text())
    def visit(node):
        known.add(node["id"])
        for child in node.get("children",[]) or []:visit(child)
    visit(raw)
    if not set(requirements) <= known:
        raise ValueError("Revision request cites an unknown requirement")
    stage = TARGETS[target]
    affected = STAGES[STAGES.index(stage):] if stage in STAGES else list(STAGES)
    record = {"id":"REV-"+uuid4().hex[:12], "status":"PENDING_REVIEW", "requesting_stage":files.stage,
        "target":target,"target_stage":stage,"issue_code":issue_code,"requirements":requirements,"source_refs":source_refs,
        "reason":reason,"proposed_change":proposed_change,"potentially_affected_stages":affected,
        "policy":"Revalidate original evidence and contracts; do not weaken acceptance or patch source ER to hide a failure"}
    save_json(files.output / ".arc/revision_requests" / (record["id"]+".json"),record)
    raise UpstreamRepairRequired(record)


def resolve_scoped_read_bindings(arc_dir):
    """Host-only narrow correction: declare read capabilities already granted by source.

    This never changes policies, business effects or free-form requested semantics.
    Other revision classes remain pending for source review.
    """
    from copy import deepcopy
    from infrastructure.utils.files import read_artifact
    from infrastructure.stages.backend.context import load_context
    from infrastructure.stages.backend.contracts import validate_backend_contracts
    from infrastructure.stages.backend.primitives import validate_design
    from infrastructure.stages.backend.platform_files import publish_routes

    requests = [p for p in (arc_dir/"revision_requests").glob("*.json")
        if (r:=json.loads(p.read_text())).get("status")=="PENDING_REVIEW" and r.get("target")=="backend_api" and r.get("issue_code")=="missing_scoped_read"]
    if not requests:return []
    tree,schema,obligations=load_context(arc_dir)
    if not tree.backend_foundation.get("enabled"):return []
    original=read_artifact(arc_dir,"backend_apis.json");design=deepcopy(original)
    policies=tree.backend_evidence["authorization"]["policies"]+tree.backend_foundation["additional_permissions"]
    resources={r["id"] for r in tree.backend_evidence["authorization"]["catalog"]["resources"]}
    if "read" not in {a["id"] for a in tree.backend_evidence["authorization"]["catalog"]["actions"]}:return []
    def allowed(role,resource,action):
        if role=="admin":return True
        rows=[r for r in policies if r["role"]==role and r["resource"]==resource and r["action"]==action]
        return any(r["effect"]=="allow" for r in rows) and not any(r["effect"]=="deny" and r["scope"]=="all" for r in rows)
    changes=[]
    roles={r["id"] for r in tree.backend_evidence["authorization"]["catalog"]["roles"]}
    for aid,api in design["apis"].items():
        if api.get("platform_builtin"):continue
        security=api["security"]
        missing=({s.split('.')[0] for s in api["read"]}&resources)-{p["resource"] for p in security["permissions"]}
        if not missing:continue
        if not security.get("resource") or not security.get("action"):return []
        actors={r for r in roles if allowed(r,security["resource"],security["action"])}
        for resource in sorted(missing):
            if not actors or not all(allowed(role,resource,"read") for role in actors):return []
            security["permissions"].append({"resource":resource,"action":"read"})
            changes.append({"api":aid,"resource":resource,"action":"read","source_actor_roles":sorted(actors)})
    if not changes:return []
    validate_design(design,obligations,tree=tree)
    validate_backend_contracts(design,tree.backend_foundation,tree.backend_evidence,schema)
    archive=arc_dir/"revisions"/("scoped-read-"+uuid4().hex[:10])
    save_json(archive/"before.json",original)
    save_json(archive/"correction.json",{"changes":changes,"policy_changed":False,
        "source_hashes":tree.backend_evidence["source_hashes"],"rerun_stages":["06_implement_backend_tdd","07_design_ui","08_implement_ui","09_design_frontend_triggers","10_implement_frontend_tdd"]})
    save_json(arc_dir/"backend_apis.json",design)
    publish_routes(arc_dir.parent,design,tree.backend_foundation)
    for p in requests:
        record=json.loads(p.read_text());record.update(status="RESOLVED_AUTOMATICALLY_RECOMPILE_REQUIRED",
            resolution="Source-permitted supporting read declarations; no role grants/effects changed",evidence=str(archive.relative_to(arc_dir.parent)))
        save_json(p,record)
    return changes
