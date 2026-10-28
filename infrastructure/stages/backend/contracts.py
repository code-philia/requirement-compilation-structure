"""Validate step 06 API interfaces and step 07 conditions over those fixed interfaces."""

import re
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

CONTRACT_KEYS = {"signature", "request", "response", "precondition", "postcondition"}
INTERFACE_KEYS = {"signature", "request", "response"}
SCHEMA_KEYS = {"type", "description", "properties", "required", "additionalProperties", "items", "enum", "const", "minLength", "maxLength", "minimum", "maximum", "pattern", "format", "minItems", "maxItems"}


def validate_shape(schema: dict) -> None:
    """Recursively validate the supported inline JSON Schema subset for request and response values."""
    if not isinstance(schema, dict) or "type" not in schema or set(schema) - SCHEMA_KEYS:
        raise ValueError("Use inline JSON Schemas with explicit type and supported keywords")
    if not isinstance(schema["type"], str) or schema["type"] not in {"object", "array", "string", "integer", "number", "boolean", "null"}:
        raise ValueError("Unsupported JSON Schema type")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ValueError(f"Invalid I/O JSON Schema: {error.message}") from error
    if schema["type"] == "object":
        if not isinstance(schema.get("properties"), dict):
            raise ValueError("Object schemas must declare properties")
        if set(schema.get("required", [])) - set(schema["properties"]):
            raise ValueError("Required properties must be declared")
        if type(schema.get("additionalProperties", False)) is not bool:
            raise ValueError("additionalProperties must be a boolean")
        for child in schema["properties"].values():
            validate_shape(child)
    if schema["type"] == "array":
        validate_shape(schema.get("items"))


def validate_interface(contract: dict) -> None:
    """Validate the fixed API interface independently of its P/Q conditions."""
    if not isinstance(contract, dict) or set(contract) != INTERFACE_KEYS:
        raise ValueError(f"API interface must contain exactly {sorted(INTERFACE_KEYS)}")
    # 1. The public function and HTTP route form the API signature.
    signature = contract["signature"]
    if not isinstance(signature, dict) or set(signature) != {"name", "method", "path"}:
        raise ValueError("signature must contain name, method, and path")
    if not isinstance(signature["name"], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", signature["name"]) or signature["name"] in {"default", "class", "function", "return", "delete", "new", "import", "export", "const", "let", "var", "await", "yield"}:
        raise ValueError("signature.name must be a TypeScript function identifier")
    if not isinstance(signature["method"], str) or signature["method"] not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError("Unsupported HTTP method")
    if not isinstance(signature["path"], str) or not re.fullmatch(r"/api(?:/[A-Za-z0-9_:-]+)+", signature["path"]) or signature["path"] == "/api/health":
        raise ValueError("Use a concrete /api/... route; /api/health is reserved")
    # 2. Request sections must match the declared route parameters.
    request = contract["request"]
    if not isinstance(request, dict) or set(request) != {"params", "query", "body", "headers"}:
        raise ValueError("request must describe params, query, body, and headers")
    for schema in request.values():
        validate_shape(schema)
        if schema["type"] != "object":
            raise ValueError("Each request section must be an object schema")
    params = set(re.findall(r":([A-Za-z_][A-Za-z0-9_]*)", signature["path"]))
    if set(request["params"]["properties"]) != params or set(request["params"].get("required", [])) != params:
        raise ValueError("Route parameters must match required request.params properties")
    # 3. Success and rejection branches define the observable response space.
    response = contract["response"]
    if not isinstance(response, dict) or set(response) != {"success", "errors"} or not isinstance(response["errors"], list):
        raise ValueError("response must contain success and errors")
    branches = [response["success"], *response["errors"]]
    statuses = set()
    for index, branch in enumerate(branches):
        if not isinstance(branch, dict) or set(branch) != {"status", "body", "headers"}:
            raise ValueError("Response branches need status, body, and headers")
        status = branch["status"]
        if type(status) is not int or not ((200 <= status < 300) if index == 0 else (400 <= status < 600 and status != 501)) or status in statuses:
            raise ValueError("Response status codes must be unique success/error statuses")
        statuses.add(status)
        validate_shape(branch["body"])
        validate_shape(branch["headers"])
        if branch["headers"]["type"] != "object":
            raise ValueError("Response headers must be an object schema")


def validate_contract(contract: dict) -> None:
    """Validate semantic P/Q records and their declared response statuses."""
    if not isinstance(contract, dict) or set(contract) != CONTRACT_KEYS:
        raise ValueError(f"Contract must contain exactly {sorted(CONTRACT_KEYS)}")
    validate_interface({key: contract[key] for key in INTERFACE_KEYS})
    branches = [contract["response"]["success"], *contract["response"]["errors"]]
    statuses = {branch["status"] for branch in branches}
    # P names a declared rejection status; Q covers every declared response status.
    ids = set()
    for kind in ("precondition", "postcondition"):
        conditions = contract[kind]
        if not isinstance(conditions, list) or (kind == "postcondition" and not conditions):
            raise ValueError(f"{kind} must be a list; postconditions must not be empty")
        for condition in conditions:
            status_key = "error_status" if kind == "precondition" else "status"
            if not isinstance(condition, dict) or set(condition) != {"id", "description", status_key}:
                raise ValueError(f"Invalid {kind} record")
            cid = condition["id"]
            if not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", cid) or cid in ids:
                raise ValueError("Condition IDs must be unique identifiers within an API")
            ids.add(cid)
            if not isinstance(condition["description"], str) or not condition["description"].strip():
                raise ValueError("Condition descriptions must not be empty")
            status = condition[status_key]
            if type(status) is not int or status not in statuses or (kind == "precondition" and status < 400):
                raise ValueError("Condition status must match a declared response branch")
    if {item["status"] for item in contract["postcondition"]} != statuses:
        raise ValueError("Each response status needs a corresponding postcondition")


def validate_registry(apis: dict, *, conditions: bool = True) -> None:
    """Validate all API contracts and reject duplicate function names or equivalent HTTP routes."""
    routes, names = set(), set()
    for api in apis.values():
        if conditions:
            validate_contract({key: api[key] for key in CONTRACT_KEYS})
        else:
            validate_interface({key: api[key] for key in INTERFACE_KEYS})
        signature = api["signature"]
        route = (signature["method"], re.sub(r":[A-Za-z_][A-Za-z0-9_]*", ":parameter", signature["path"]))
        if route in routes or signature["name"] in names:
            raise ValueError("API signatures and HTTP routes must be unambiguous")
        routes.add(route)
        names.add(signature["name"])


def validate_contracts(value: dict, design: dict) -> None:
    """Ensure P/Q inference preserves allocations, descriptions, R/W and I/O interfaces."""
    if not isinstance(value, dict) or set(value) != {"apis", "requirements"} or not isinstance(value["apis"], dict) or value["requirements"] != design["requirements"] or set(value["apis"]) != set(design["apis"]):
        raise ValueError("Contract bindings must exactly match Backend API Decomposition")
    for aid, api in value["apis"].items():
        if not isinstance(api, dict) or set(api) != CONTRACT_KEYS | {"description", "read", "write"}:
            raise ValueError(f"Invalid completed API Primitive: {aid}")
        if {key: api[key] for key in ("description", "read", "write", "signature", "request", "response")} != design["apis"][aid]:
            raise ValueError(f"Contract Inference cannot change API decomposition, obligations, or interface: {aid}")
    validate_registry(value["apis"])
