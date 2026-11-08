"""Read versioned authorization/process evidence without business-specific inference."""

import csv
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from infrastructure.stages.requirements.images import input_file, requirement_nodes
from infrastructure.utils.files import read_artifact, save_json

NS = {"b": "http://www.omg.org/spec/BPMN/20100524/MODEL"}
SCOPES = {"all", "own", "unit", "unit_tree", "assigned"}


def compile_evidence(raw, input_dir):
    root = Path(input_dir).resolve()
    evidence = {"enabled": False, "authorization": {}, "processes": {}, "nodes": {},
        "source_hashes": {}, "diagnostics": []}
    def read(relative):
        path = input_file(root, relative)
        data = path.read_bytes()
        evidence["source_hashes"][relative] = hashlib.sha256(data).hexdigest()
        return data.decode("utf-8-sig")
    catalog_path = "reference/authorization/catalog.json"
    if (root / catalog_path).exists():
        catalog = json.loads(read(catalog_path))
        ids = {}
        for key in ("roles", "resources", "actions", "units"):
            rows = catalog.get(key)
            if not isinstance(rows, list) or any(not isinstance(row.get("id"), str) for row in rows):
                raise ValueError(f"Invalid authorization catalog: {key}")
            ids[key] = {row["id"] for row in rows}
            if len(ids[key]) != len(rows):
                raise ValueError(f"Duplicate authorization catalog IDs: {key}")
        model = read("reference/authorization/model.conf")
        if "r = sub, unit, obj, act, owner, rec_unit, assignee" not in model or "g = _, _, _" not in model or "p = role, obj, act, scope, eft" not in model:
            raise ValueError("Unsupported authorization model: expected bundle domain-RBAC request contract")
        policies, hierarchy = [], []
        for row in csv.reader(read("reference/authorization/policy.csv").splitlines(), skipinitialspace=True):
            if not row:
                continue
            row = [value.strip() for value in row]
            if row[0] == "p" and len(row) == 6:
                _, role, resource, action, scope, effect = row
                if role not in ids["roles"] or resource not in ids["resources"] or action not in ids["actions"] or scope not in SCOPES or effect not in {"allow", "deny"}:
                    raise ValueError(f"Invalid authorization policy: {row}")
                policies.append({"role": role, "resource": resource, "action": action, "scope": scope, "effect": effect})
            elif row[0] == "g2" and len(row) == 3 and set(row[1:]) <= ids["units"]:
                hierarchy.append(row[1:])
            else:
                raise ValueError(f"Unsupported authorization policy row: {row}")
        units = {row["id"]: row for row in catalog["units"]}
        for code, unit in units.items():
            seen, current = set(), code
            while current is not None:
                if current in seen or current not in units:
                    raise ValueError(f"Invalid organization hierarchy at {code}")
                seen.add(current)
                current = units[current].get("parent")
        expected_hierarchy={(code,row.get("parent")) for code,row in units.items() if row.get("parent") is not None}
        if set(map(tuple,hierarchy)) != expected_hierarchy:
            raise ValueError("Authorization catalog/policy organization hierarchies disagree")
        evidence["authorization"] = {"catalog": catalog, "model": model, "policies": policies, "hierarchy": hierarchy}
        evidence["enabled"] = True
        if policies and all(row["scope"] == "all" for row in policies):
            evidence["diagnostics"].append({"code": "POLICY_SCOPE_REQUIRES_SEMANTIC_REVIEW", "message": "All source policies use all. Prose/scenarios may impose an additional tenant/unit boundary; normalize it explicitly."})
    index_path = "reference/bpmn/index.json"
    if (root / index_path).exists():
        for item in json.loads(read(index_path)):
            pid = item["id"]
            if pid in evidence["processes"]:
                raise ValueError(f"Duplicate process {pid}")
            relative = "reference/bpmn/" + item["xml"]
            try:
                doc = ET.fromstring(read(relative))
            except ET.ParseError as error:
                raise ValueError(f"Invalid BPMN XML {relative}: {error}") from error
            process = doc.find("b:process", NS)
            if process is None or process.get("id") != pid:
                raise ValueError(f"Invalid BPMN index reference: {pid}")
            roles = {}
            for lane in process.findall(".//b:lane", NS):
                role = lane.get("name")
                if evidence["authorization"] and role not in ids["roles"]:
                    raise ValueError(f"{pid}: unknown lane role {role}")
                for ref in lane.findall("b:flowNodeRef", NS):
                    if ref.text in roles:
                        raise ValueError(f"{pid}: duplicate lane membership for {ref.text}")
                    roles[ref.text] = role
            nodes, flows = {}, []
            for element in process:
                kind = element.tag.rsplit("}", 1)[-1]
                identifier = element.get("id")
                if kind == "laneSet":
                    continue
                if kind == "sequenceFlow":
                    flows.append({"id": identifier, "source": element.get("sourceRef"), "target": element.get("targetRef"),
                        "condition": element.findtext("b:conditionExpression", default="", namespaces=NS)})
                elif identifier:
                    if identifier in nodes:
                        raise ValueError(f"{pid}: duplicate node {identifier}")
                    nodes[identifier] = {"id": identifier, "kind": kind, "name": element.get("name", ""), "role": roles.get(identifier)}
            for flow in flows:
                if flow["source"] not in nodes or flow["target"] not in nodes:
                    raise ValueError(f"{pid}: unresolved flow endpoints")
            for node in nodes.values():
                if node["kind"] in {"userTask", "manualTask"} and not node["role"]:
                    raise ValueError(f"{pid}/{node['id']}: human task requires a role lane")
                if node["kind"] == "exclusiveGateway":
                    evidence["diagnostics"].append({"code": "BPMN_BRANCH_REVIEW", "process": pid, "node": node["id"],
                        "message": "Verify mutual exclusivity against source scenarios; natural-language conditions are not executable guards."})
            evidence["processes"][pid] = {"id": pid, "name": process.get("name", ""), "source": relative,
                "executable": process.get("isExecutable") == "true", "nodes": nodes, "flows": flows}
        evidence["enabled"] = evidence["enabled"] or bool(evidence["processes"])
    coverage_path="reference/bpmn/coverage.json"
    if (root / coverage_path).exists():
        evidence["process_coverage"]=json.loads(read(coverage_path))
    all_policy_rows = {", ".join(["p", row["role"], row["resource"], row["action"], row["scope"], row["effect"]]) for row in evidence["authorization"].get("policies", [])}
    for node in requirement_nodes(raw):
        description = node.get("description", {})
        description = description if isinstance(description, dict) else {"text": description}
        processes = []
        for reference in description.get("bpmn", []) or []:
            path, _, fragment = reference.partition("#")
            pid, _, nid = fragment.partition("/")
            process = evidence["processes"].get(pid)
            if not process or path != process["source"] or (nid and nid not in process["nodes"]):
                raise ValueError(f"{node['id']}: unresolved process reference {reference}")
            processes.append(pid)
        for row in description.get("authorization", []) or []:
            if row not in all_policy_rows:
                raise ValueError(f"{node['id']}: unresolved authorization reference {row}")
        evidence["nodes"][node["id"]] = {"id": node["id"], "name": node.get("name", ""),
            "text": description.get("text", "").split("[explore-ui]", 1)[0],
            "observed_ui_text": description.get("text", "").partition("[explore-ui]")[2],
            "dependencies": node.get("dependencies", []), "processes": list(dict.fromkeys(processes)),
            "authorization": description.get("authorization", []), "er": description.get("er", []),
            "scenarios": node.get("scenarios", []), "children": [c["id"] for c in node.get("children", []) or []]}
    for node in evidence["nodes"].values():
        if not set(node["dependencies"]) <= set(evidence["nodes"]):
            raise ValueError(f"{node['id']}: unknown dependency")
    return evidence


def scoped_evidence(evidence, rid, resources=()):
    if not evidence or not evidence.get("enabled"):
        return {}
    nodes = evidence["nodes"]
    selected, pending = set(), [rid]
    while pending:
        current = pending.pop()
        if current in selected:
            continue
        selected.add(current)
        pending.extend(nodes[current]["dependencies"])
        pending.extend(nodes[current]["children"] if current != rid else [])
    parents = {child:key for key,node in nodes.items() for child in node["children"]}
    ancestors = set()
    for key in list(selected):
        while key in parents:
            key = parents[key]
            ancestors.add(key)
    context = selected | ancestors
    processes = {pid for key in context for pid in nodes[key]["processes"]}
    policies = evidence["authorization"].get("policies", [])
    cited = {row.split(", ")[2] for key in context for row in nodes[key]["authorization"]}
    wanted = set(resources) | cited
    return {"requirement": nodes[rid], "dependency_context": [nodes[key] for key in sorted(selected - {rid})],
        "ancestor_context": [nodes[key] for key in sorted(ancestors - selected)],
        "authorization": {**evidence["authorization"], "policies": [row for row in policies if row["resource"] in wanted]},
        "processes": {key: evidence["processes"][key] for key in sorted(processes)},
        "diagnostics": evidence["diagnostics"], "source_hashes": evidence["source_hashes"]}


def load_evidence(arc_dir):
    path = arc_dir / "backend_evidence.json"
    return read_artifact(arc_dir, path.name) if path.is_file() else {}
