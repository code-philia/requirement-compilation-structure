"""Validate signature, I/O schemas, and P/Q bindings without changing R/W."""

import re
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

CONTRACT_KEYS = {"signature", "request", "response", "precondition", "postcondition"}
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


def resolve_field(schema: dict, pointer: str) -> None:
    """Verify that a condition's JSON Pointer resolves to an existing field in its I/O schema."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Use a JSON Pointer to bind a condition to an I/O field: {pointer}")
    current = schema
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if current.get("type") == "object" and token in current.get("properties", {}):
            current = current["properties"][token]
        elif current.get("type") == "array" and token.isdigit():
            current = current["items"]
        else:
            raise ValueError(f"Condition references an unknown I/O field: {pointer}")


def validate_contract(contract: dict) -> None:
    """Validate the API signature, request/response branches, and P/Q field bindings without changing its obligations."""
    if not isinstance(contract, dict) or set(contract) != CONTRACT_KEYS:
        raise ValueError(f"Contract must contain exactly {sorted(CONTRACT_KEYS)}")
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
    # 4. Bind P to request fields and Q to fields of a declared response branch.
    ids = set()
    for kind, fields_key in (("precondition", "request_fields"), ("postcondition", "response_fields")):
        conditions = contract[kind]
        if not isinstance(conditions, list) or (kind == "postcondition" and not conditions):
            raise ValueError(f"{kind} must be a list; postconditions must not be empty")
        for condition in conditions:
            status_key = "error_status" if kind == "precondition" else "status"
            if not isinstance(condition, dict) or set(condition) != {"id", "description", fields_key, status_key}:
                raise ValueError(f"Invalid {kind} record")
            cid = condition["id"]
            if not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", cid) or cid in ids:
                raise ValueError("Condition IDs must be unique identifiers within an API")
            ids.add(cid)
            if not isinstance(condition["description"], str) or not condition["description"].strip():
                raise ValueError("Condition descriptions must not be empty")
            if not isinstance(condition[fields_key], list) or not condition[fields_key]:
                raise ValueError("Each condition must bind at least one I/O field")
            status = condition[status_key]
            if type(status) is not int or status not in statuses or (kind == "precondition" and status < 400):
                raise ValueError("Condition status must match a declared response branch")
            if kind == "precondition":
                root = {"type": "object", "properties": request}
            else:
                branch = next(item for item in branches if item["status"] == status)
                root = {"type": "object", "properties": {"body": branch["body"], "headers": branch["headers"], "status": {"type": "integer"}}}
            for pointer in condition[fields_key]:
                resolve_field(root, pointer)
    if {item["status"] for item in contract["postcondition"]} != statuses:
        raise ValueError("Each response status needs a corresponding postcondition")


def validate_registry(apis: dict) -> None:
    """Validate all API contracts and reject duplicate function names or equivalent HTTP routes."""
    routes, names = set(), set()
    for api in apis.values():
        validate_contract({key: api[key] for key in CONTRACT_KEYS})
        signature = api["signature"]
        route = (signature["method"], re.sub(r":[A-Za-z_][A-Za-z0-9_]*", ":parameter", signature["path"]))
        if route in routes or signature["name"] in names:
            raise ValueError("API signatures and HTTP routes must be unambiguous")
        routes.add(route)
        names.add(signature["name"])


def validate_contracts(value: dict, design: dict) -> None:
    """Ensure completed contracts preserve the API decomposition, requirement bindings, descriptions, and read/write sets."""
    if not isinstance(value, dict) or set(value) != {"apis", "requirements"} or not isinstance(value["apis"], dict) or value["requirements"] != design["requirements"] or set(value["apis"]) != set(design["apis"]):
        raise ValueError("Contract bindings must exactly match Backend API Decomposition")
    for aid, api in value["apis"].items():
        if not isinstance(api, dict) or set(api) != CONTRACT_KEYS | {"description", "read", "write"}:
            raise ValueError(f"Invalid completed API Primitive: {aid}")
        if {key: api[key] for key in ("description", "read", "write")} != design["apis"][aid]:
            raise ValueError(f"Contract Inference cannot change Dataflow Obligations: {aid}")
    validate_registry(value["apis"])
