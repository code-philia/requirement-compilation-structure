"""Model-free acceptance oracle from original scenarios and external data."""

import hashlib
import json
import re


def source_expectations(raw, rid):
    source_hash = hashlib.sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    def find(node):
        if node["id"] == rid:return node
        for child in node.get("children",[]) or []:
            result = find(child)
            if result:return result
    node = find(raw)
    if node is None:raise ValueError(f"Unknown source requirement {rid}")
    data_ids = node.get("data",{}).get("requires",[]) if isinstance(node.get("data"),dict) else []
    records = []
    for record in raw.get("data",[]):
        if record["id"] not in data_ids:continue
        if record["entity"] == "test account":
            record = {**record,"properties":{k:v for k,v in record["properties"].items() if k!="password"}}
        records.append(record)
    return {"source_sha256":source_hash,"requirement":rid,"description":node["description"],
        "scenarios":node.get("scenarios",[]),"data":records,
        "authority":"Original source, independent of generated UI/API/state-machine designs"}


def test_accounts(raw):
    """Credentials from explicit test fixtures, supplied only to acceptance generation."""
    return [{"record_id":r["id"],**r["properties"]} for r in raw.get("data",[])
        if r["entity"] == "test account" and r["lifecycle"] == "SEED"]


def require_scenario_coverage(report, expectations):
    cases = report.get("cases",[])
    missing = [s["id"] for s in expectations["scenarios"] if not any(re.search(r'(?<![A-Za-z0-9_.-])'+re.escape(s["id"])+r'(?![A-Za-z0-9_.-])',c["title"]) for c in cases)]
    if missing:
        raise ValueError(f"Acceptance omitted source scenarios in executed test titles: {missing}")
