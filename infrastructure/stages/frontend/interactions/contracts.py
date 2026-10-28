"""Interaction P/Q and typed request/update mappings against fixed API contracts."""

from jsonschema import Draft202012Validator

from infrastructure.stages.frontend.interactions.design import IDENTITY, data_types, identifiers, require_fields, text


def schema_at(root, pointer):
    """Resolve a JSON Pointer into a supported request/response schema and return the referenced subschema."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("Use a JSON Pointer to identify an API field")
    current = root
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if current.get("type") == "object" and token in current.get("properties", {}):
            current = current["properties"][token]
        elif current.get("type") == "array" and token.isdigit():
            current = current["items"]
        else:
            raise ValueError(f"Unknown API field: {pointer}")
    return current


def request_schema(api):
    """Wrap the canonical API request sections as one object schema for mapping validation."""
    return {"type": "object", "properties": api["request"], "required": list(api["request"])}


def required_fields(schema, prefix=""):
    """List recursively required object-field pointers in a request schema."""
    if schema["type"] != "object" or not schema.get("required"):
        return [prefix]
    return [pointer for key in schema.get("required", [])
        for pointer in required_fields(schema["properties"][key], prefix + "/" + key.replace("~", "~0").replace("/", "~1"))]


def compatible(source, target):
    """Check data-type assignability, allowing integer values where a number is expected."""
    return source == target or (source == "integer" and target == "number")


def expression_type(expr, variables, calls, event_triggers):
    """Expressions are descriptions/data, never evaluated as generated code."""
    if not isinstance(expr, dict) or not isinstance(expr.get("source"), str):
        raise ValueError("Use a structured data/literal/input/response/transform expression")
    source = expr["source"]
    if source == "data":
        require_fields(expr, {"source", "var"}, "data expression")
        if not isinstance(expr["var"], str) or expr["var"] not in variables:
            raise ValueError(f"Unknown frontend variable: {expr['var']}")
        return variables[expr["var"]], {expr["var"]}
    if source == "literal":
        require_fields(expr, {"source", "value"}, "literal expression")
        value = expr["value"]
        kind = "null" if value is None else "boolean" if isinstance(value, bool) else "integer" if isinstance(value, int) else "number" if isinstance(value, float) else "string" if isinstance(value, str) else "array" if isinstance(value, list) else "object"
        return kind, set()
    if source == "input":
        require_fields(expr, {"source", "field"}, "input expression")
        allowed = {"value": ({"change", "input"}, "string"), "checked": ({"change", "input"}, "boolean"),
            "key": ({"keydown", "keyup"}, "string")}
        if not isinstance(expr["field"], str) or expr["field"] not in allowed:
            raise ValueError("Native input fields are value, checked, or key")
        interactions, dtype = allowed[expr["field"]]
        if not event_triggers or any(trigger["event"] not in interactions for trigger in event_triggers):
            raise ValueError("Native input mappings must match every trigger using this event")
        return dtype, set()
    if source == "response":
        require_fields(expr, {"source", "call", "status", "field"}, "response expression")
        if not isinstance(expr["call"], str) or expr["call"] not in calls or type(expr["status"]) is not int:
            raise ValueError("Response mappings may use only earlier API call results")
        api = calls[expr["call"]]
        branch = next((branch for branch in [api["response"]["success"], *api["response"]["errors"]] if branch["status"] == expr["status"]), None)
        if branch is None:
            raise ValueError("Unknown API response status")
        if isinstance(expr["field"], str) and expr["field"].startswith("/headers/"):
            header = expr["field"].split("/")[2].lower()
            if header in {"set-cookie", "cookie"}:
                raise ValueError("Browser cookie transport is not readable frontend response data")
        root = {"type": "object", "properties": {"body": branch["body"], "headers": branch["headers"], "status": {"type": "integer"}}}
        return schema_at(root, expr["field"])["type"], set()
    if source == "transform":
        require_fields(expr, {"source", "operation", "inputs", "dtype"}, "transform expression")
        text(expr["operation"], "transform operation")
        if not isinstance(expr["inputs"], list) or not isinstance(expr["dtype"], str) or expr["dtype"] not in {"string", "number", "integer", "boolean", "array", "object", "null"}:
            raise ValueError("A transform needs inputs and a declared result dtype")
        dependencies = set()
        for item in expr["inputs"]:
            _, reads = expression_type(item, variables, calls, event_triggers)
            dependencies.update(reads)
        return expr["dtype"], dependencies
    raise ValueError(f"Unsupported expression source: {source}")


def response_sources(expr):
    """Collect action-response references used by a declarative event expression."""
    if expr.get("source") == "response":
        yield expr
    for child in expr.get("inputs", []):
        yield from response_sources(child)


def validate_mapping(expr, target, action, variables, calls, event_triggers):
    """Validate a declared event expression against its target API field type and required object fields."""
    dtype, reads = expression_type(expr, variables, calls, event_triggers)
    if not compatible(dtype, target["type"]) or not reads.issubset(action["read"]):
        raise ValueError(f"Mapping type/read mismatch at {action['id']}: {dtype} -> {target['type']}; reads={sorted(reads)}")
    if expr["source"] == "literal":
        errors = list(Draft202012Validator(target).iter_errors(expr["value"]))
        if errors:
            raise ValueError(f"Literal does not satisfy API/data schema: {errors[0].message}")
    for ref in response_sources(expr):
        if not action["when"] or ref["call"] not in action["when"] or str(ref["status"]) not in action["when"]:
            raise ValueError(f"Response-dependent action needs a when condition naming call ID and status: {action['id']}")


def validate_contract(eid, contract, interactions, ui, backend):
    """Validate event P/Q conditions and typed action/update mappings against UI data and canonical backend contracts."""
    require_fields(contract, {"precondition", "postcondition", "actions"}, eid + " contract")
    event = interactions["events"][eid]
    triggers = [trigger for trigger in interactions["triggers"].values() if trigger["action"] == eid]
    variables = data_types(ui)
    actions = {action["id"]: action for action in event["actions"]}
    if not isinstance(contract["actions"], dict) or set(contract["actions"]) != set(actions):
        raise ValueError("Provide one action contract for every event action")
    calls = {}
    for action in event["actions"]:
        aid, kind = action["id"], action["kind"]
        mapping = contract["actions"][aid]
        if kind == "local":
            require_fields(mapping, {"updates", "assertions"}, aid)
            if not isinstance(mapping["updates"], dict) or set(mapping["updates"]) != set(action["write"]):
                raise ValueError(f"Local updates must implement exactly the declared frontend writes: {aid}")
            if not isinstance(mapping["assertions"], list) or any(not isinstance(item, str) or not item.strip() for item in mapping["assertions"]):
                raise ValueError("Local assertions are English semantic validation rules")
            for var, expression in mapping["updates"].items():
                validate_mapping(expression, {"type": variables[var]}, action, variables, calls, triggers)
        elif kind == "navigate":
            require_fields(mapping, set(), aid + " navigation contract")
        else:
            require_fields(mapping, {"request", "credentials"}, aid)
            if not isinstance(mapping["request"], dict) or not isinstance(mapping["credentials"], str) or mapping["credentials"] not in {"include", "same-origin", "omit"}:
                raise ValueError("API mappings need request fields and browser credentials policy")
            api = backend["apis"][action["api"]]
            if mapping["credentials"] == "omit" and any("set-cookie" in branch["headers"].get("properties", {})
                    for branch in [api["response"]["success"], *api["response"]["errors"]]):
                raise ValueError("Browser credentials must preserve the API's declared Set-Cookie effects")
            root = request_schema(api)
            pointers = list(mapping["request"])
            if any(pointer.startswith(other + "/") for pointer in pointers for other in pointers if pointer != other):
                raise ValueError("Do not map both a request object and one of its descendants")
            for pointer, expression in mapping["request"].items():
                target = schema_at(root, pointer)
                if pointer == "/headers/cookie":
                    require_fields(expression, {"source", "name"}, "browser transport")
                    if expression != {"source": "transport", "name": "cookie"} or mapping["credentials"] == "omit" or target["type"] != "string":
                        raise ValueError("Cookie request headers must use automatic browser transport with credentials")
                else:
                    validate_mapping(expression, target, action, variables, calls, triggers)
            required = [pointer for section, shape in api["request"].items()
                for key in shape.get("required", [])
                for pointer in required_fields(shape["properties"][key], "/" + section + "/" + key.replace("~", "~0").replace("/", "~1"))]
            for pointer in required:
                if pointer and not any(pointer == mapped or pointer.startswith(mapped + "/") for mapped in pointers):
                    raise ValueError(f"Required API request field has no source: {aid} {pointer}")
            calls[aid] = api
    ids, covered_actions, covered_writes, branches, upstream_conditions = set(), set(), set(), set(), set()
    for kind in ("precondition", "postcondition"):
        if not isinstance(contract[kind], list) or (kind == "postcondition" and not contract[kind]):
            raise ValueError("P must be a list and Q must be a nonempty list")
        for condition in contract[kind]:
            fields = {"id", "description", "read"} if kind == "precondition" else {"id", "description", "actions", "write", "outcome", "api_conditions", "page"}
            require_fields(condition, fields, kind)
            cid = condition["id"]
            if not isinstance(cid, str) or not IDENTITY.fullmatch(cid) or not cid.startswith("P-" if kind == "precondition" else "Q-") or cid in ids:
                raise ValueError("Use unique P-/Q- condition IDs within an event")
            ids.add(cid)
            text(condition["description"], cid)
            if kind == "precondition":
                allowed_reads = set(event["read"]) | {var for trigger in triggers for var in trigger["read"]}
                identifiers(condition["read"], allowed_reads, cid)
                continue
            assigned = identifiers(condition["actions"], actions, cid + ".actions")
            if not assigned:
                raise ValueError("Each Q needs at least one action reference")
            writes = identifiers(condition["write"], event["write"], cid + ".write")
            if not writes.issubset({var for aid in assigned for var in actions[aid]["write"]}):
                raise ValueError("Q writes must be produced by its referenced actions")
            covered_actions.update(assigned)
            covered_writes.update(writes)
            if condition["page"] is not None:
                if not isinstance(condition["page"], str) or condition["page"] not in ui["pages"] or not any(actions[aid]["kind"] == "navigate" and actions[aid]["page"] == condition["page"] for aid in assigned):
                    raise ValueError("Q navigation page needs a matching navigation action")
            outcome = condition["outcome"]
            if outcome is None:
                if condition["api_conditions"] != []:
                    raise ValueError("API condition references need an explicit call outcome")
            else:
                require_fields(outcome, {"call", "status"}, "Q outcome")
                if not isinstance(outcome["call"], str) or outcome["call"] not in calls or outcome["call"] not in assigned or type(outcome["status"]) is not int:
                    raise ValueError("Q outcome needs an API action reference and status")
                api = calls[outcome["call"]]
                eligible = {item["id"] for item in api["postcondition"] if item["status"] == outcome["status"]}
                identifiers(condition["api_conditions"], eligible, cid + ".api_conditions")
                if not eligible or not condition["api_conditions"]:
                    raise ValueError("Trace Q to the upstream API postconditions of the declared response status")
                branches.add((outcome["call"], outcome["status"]))
                upstream_conditions.update((outcome["call"], qid) for qid in condition["api_conditions"])
    if covered_actions != set(actions) or covered_writes != set(event["write"]):
        raise ValueError("Postconditions must cover every event action and frontend write")
    for aid, api in calls.items():
        expected_branches = {(aid, branch["status"]) for branch in [api["response"]["success"], *api["response"]["errors"]]}
        if not expected_branches.issubset(branches) or any((aid, condition["id"]) not in upstream_conditions for condition in api["postcondition"]):
            raise ValueError(f"Q must cover all response branches and upstream postconditions: {aid}")
