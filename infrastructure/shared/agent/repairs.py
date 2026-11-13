"""Auditable upstream revision requests; application agents cannot edit contracts."""

import json
from uuid import uuid4

from infrastructure.utils.files import save_json

TARGETS = {
    "schema": "build_db_schema", "backend_foundation": "build_backend",
    "obligations": "analyze_db_requirements", "backend_api": "build_backend",
    "ui_design": "build_frontend", "triggers": "build_frontend",
    "acceptance": "build_frontend", "validation_data": "implement_db",
    "input_evidence": "read_requirements", "compiler_runtime": "compiler_maintenance",
}


class UpstreamRepairRequired(RuntimeError):
    def __init__(self, record):
        self.revision_request = record
        super().__init__(f"Upstream revision required: {record['id']} → {record['target_stage']}: {record['reason']}")


def request_design_revision(files, target, requirements, source_refs, reason, proposed_change, issue_code="other"):
    if target not in TARGETS or not requirements or not source_refs or not reason.strip() or not proposed_change.strip():
        raise ValueError("An upstream revision needs a known target, requirement IDs, evidence and a concrete change")
    if not isinstance(requirements,list) or not isinstance(source_refs,list) or any(not isinstance(x,str) or not x.strip() for x in requirements+source_refs):
        raise ValueError("requirements/source_refs must be nonempty string arrays")
    if issue_code not in {"other", "missing_scoped_read"}:
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
    # Resolve at call time to avoid compiler/stage import cycles and stale stage lists.
    from infrastructure.compiler import PIPELINE
    stages = [name for name, _, _ in PIPELINE]
    affected = stages[stages.index(stage):] if stage in stages else stages
    record = {"id":"REV-"+uuid4().hex[:12], "status":"PENDING_REVIEW", "requesting_stage":files.stage,
        "target":target,"target_stage":stage,"issue_code":issue_code,"requirements":requirements,"source_refs":source_refs,
        "reason":reason,"proposed_change":proposed_change,"potentially_affected_stages":affected,
        "policy":"Revalidate original evidence and contracts; do not weaken acceptance or patch source ER to hide a failure"}
    save_json(files.output / ".arc/revision_requests" / (record["id"]+".json"),record)
    raise UpstreamRepairRequired(record)
