"""Backend contract structure, module call graph and obligation propagation."""

import re

from infrastructure.stages.database.obligation_utils import check_symbols, normalize_record, union
from infrastructure.stages.backend.primitives import coverage, ObligationCoverageError


def validate_http_signature(identity, signature):
    method, path = signature["method"], signature["path"]
    methods = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
    if not isinstance(method, str) or method not in methods:
        raise ValueError(f"{identity}.signature.method={method!r}; use an uppercase HTTP method: {sorted(methods)}")
    if not isinstance(path, str) or not re.fullmatch(r"/api/[^?#\s]+", path):
        raise ValueError(f"{identity}.signature.path={path!r} must be a backend data endpoint under /api/, "
            "e.g. /api/session/current. Frontend renders page URLs such as / and /login; "
            "design a JSON data endpoint instead of a server-rendered page")
    return method, path


def validate_backend_design(design, schema, obligations, tree, *, complete=False):
    """Validate the full accepted graph and every already associated requirement."""
    apis, modules = design["apis"], design["modules"]
    if set(apis) & set(modules):
        raise ValueError("API and module IDs must be globally distinct")
    records = {**apis, **modules}
    signatures, routes = set(), set()
    for identity, record in records.items():
        for key in ("description", "read", "write", "precondition", "postcondition", "callees"):
            if key not in record:
                raise ValueError(f"Missing {identity}.{key}")
        if not isinstance(record["description"], str) or not record["description"].strip():
            raise ValueError(f"{identity} needs a business description")
        normalized = normalize_record(record)
        record.update(normalized)
        check_symbols([record], schema)
        callees = record["callees"]
        if not isinstance(callees, list) or any(not isinstance(item, str) for item in callees):
            raise ValueError(f"{identity}.callees must be module IDs")
        if len(callees) != len(set(callees)) or any(item not in modules for item in callees):
            raise ValueError(f"{identity} has duplicate or undefined module callees: {callees}")
        for key in ("precondition", "postcondition"):
            if not isinstance(record[key], list):
                raise ValueError(f"{identity}.{key} must be an array")
            for condition in record[key]:
                if not condition["id"] or not condition["description"].strip():
                    raise ValueError(f"{identity} needs named, described conditions")
        name = record["signature"]["name"] if identity in apis else record["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in signatures:
            raise ValueError(f"Invalid or duplicate backend function name: {name}")
        signatures.add(name)
        if identity in apis:
            method, path = validate_http_signature(identity, record["signature"])
            if (method, path) in routes:
                raise ValueError(f"Duplicate HTTP route: {method} {path}")
            routes.add((method, path))
            for key in ("params", "query", "body", "headers"):
                if not isinstance(record["request"][key], dict):
                    raise ValueError(f"{identity}.request.{key} must be an inline JSON schema")
            responses = [record["response"]["success"], *record["response"]["errors"]]
            for response in responses:
                if type(response["status"]) is not int or not 100 <= response["status"] <= 599 or response["status"] == 501:
                    raise ValueError(f"Invalid HTTP response status for {identity}")
                if not isinstance(response["body"], dict) or not isinstance(response["headers"], dict):
                    raise ValueError(f"{identity} responses require body/header JSON schemas")
            statuses = {response["status"] for response in responses}
            for condition in record["precondition"]:
                if condition["error_status"] not in statuses:
                    raise ValueError(f"{identity} precondition error must have a declared response")
            for condition in record["postcondition"]:
                if condition["status"] not in statuses:
                    raise ValueError(f"{identity} postcondition status must have a declared response")
        else:
            if not isinstance(record["input"], dict) or not isinstance(record["output"], dict):
                raise ValueError(f"{identity} requires input/output inline JSON schemas")
            direct = {"read": record["direct_read"], "write": record["direct_write"]}
            check_symbols([direct], schema)

    # Visit callees first; obligation summaries are inclusive of all called modules.
    finished, visiting = set(), set()

    def visit(identity):
        if identity in finished:
            return
        if identity in visiting:
            raise ValueError(f"Cyclic backend module calls at {identity}")
        visiting.add(identity)
        record = records[identity]
        children = []
        for callee in record["callees"]:
            visit(callee)
            children.append(modules[callee])
        if identity in modules:
            children.append({"read": record["direct_read"], "write": record["direct_write"]})
        expected = union(children)
        if normalize_record(record) != expected:
            raise ValueError(f"{identity} read/write must equal direct DB effects plus callee effects: {expected}")
        visiting.remove(identity)
        finished.add(identity)

    for identity in records:
        visit(identity)
    # callers is derived so shared module reuse never needs reciprocal edit calls.
    for record in records.values():
        record["callers"] = []
    for identity, record in records.items():
        for callee in record["callees"]:
            modules[callee]["callers"].append(identity)
    for record in records.values():
        record["callers"].sort()

    expected = tree.requirements if complete else design["requirements"]
    for rid in expected:
        if tree.children[rid]:
            continue
        api_ids = design["requirements"][rid]
        module_ids = design["requirement_modules"][rid]
        if len(api_ids) != len(set(api_ids)) or len(module_ids) != len(set(module_ids)):
            raise ValueError(f"Duplicate requirement associations: {rid}")
        selected = [apis[key] for key in api_ids] + [modules[key] for key in module_ids]
        required = obligations["requirements"][rid]
        gaps = coverage(required, selected)
        if any(fields for group in gaps.values() for fields in group.values()):
            raise ObligationCoverageError(rid, required, union(selected), gaps)
        combined = union(selected)
        for sid in tree.own_steps[rid]:
            step = obligations["steps"][sid]
            for mode in ("read", "write"):
                if set(step[mode]) - set(combined[mode]):
                    raise ValueError(f"Backend design does not cover {sid}.{mode}")
