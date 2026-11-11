"""Incremental API and module design using native function tool calls."""

from copy import deepcopy
import json
import re

from infrastructure.shared.agent.agent import BaseAgent
from infrastructure.shared.agent.conventions import merge_conventions
from infrastructure.shared.models.text import reasoning_arguments
from infrastructure.stages.backend.design import validate_backend_design, validate_http_signature
from infrastructure.utils.presentation.formatting import format_schema
from infrastructure.utils.presentation.model_io import record_tool_execution


STRING = {"type": "string"}
STRINGS = {"type": "array", "items": STRING}
FUNCTION_NAME = {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
    "description": "Unique implementation function name, e.g. resolveCurrentUser; separate from the stable contract id."}
JSON_SCHEMA = {"type": "object", "additionalProperties": True,
    "description": "Inline JSON Schema describing the value, not example data. Declare object properties/required and array items where applicable."}
CONDITIONS = {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string", "description": "Stable condition identifier"},
    "description": {"type": "string", "description": "Business assumption or guaranteed outcome, including applicable branches"}},
    "required": ["id", "description"], "additionalProperties": False}}
COMMON = {
    "description": {"type": "string", "description": "Business responsibility, call sequence, input mapping, result composition and failure handling"},
    "read": {**STRINGS, "description": "Total qualified Entity.field reads, including all callee effects; [] when none"},
    "write": {**STRINGS, "description": "Total qualified Entity.field writes across supported branches, including callee effects; [] when none"},
    "precondition": {**CONDITIONS, "description": "Input/state assumptions and supported rejection conditions; [] if unconditional"},
    "postcondition": {**CONDITIONS, "description": "Output and persistent-state guarantees for supported branches"},
    "callees": {**STRINGS, "uniqueItems": True,
        "description": "IDs of directly called modules only. Callers are derived by the compiler and must not be supplied."},
}
MODULE = {"type": "object", "description": "Complete internal module contract, also required for updates",
    "properties": {**COMMON, "name": FUNCTION_NAME,
        "input": {**JSON_SCHEMA, "description": "Inline JSON Schema of the module's input arguments"},
        "output": {**JSON_SCHEMA, "description": "Inline JSON Schema of the module's result, including specified business failure branches"},
        "direct_read": {**STRINGS, "description": "Qualified DB fields read by this module itself, excluding callee accesses"},
        "direct_write": {**STRINGS, "description": "Qualified DB fields written by this module itself, excluding callee accesses"}},
    "required": [*COMMON, "name", "input", "output", "direct_read", "direct_write"], "additionalProperties": False}
HTTP_RESULT = {"type": "object", "properties": {
    "status": {"type": "integer", "minimum": 100, "maximum": 599, "not": {"const": 501},
        "description": "HTTP status for this specified business outcome; 501 is reserved for implementation stubs"},
    "body": {**JSON_SCHEMA, "description": "Inline JSON Schema of the response body; use type=null for an empty body"},
    "headers": {**JSON_SCHEMA, "description": "Inline JSON Schema of response headers with lower-case names"}},
    "required": ["status", "body", "headers"], "additionalProperties": False}
API = {"type": "object", "description": "Complete HTTP data endpoint contract, also required for updates",
    "properties": {**COMMON,
        "signature": {"type": "object", "properties": {
            "name": FUNCTION_NAME,
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
                "description": "Uppercase HTTP method"},
            "path": {"type": "string", "pattern": "^/api/[^?#\\s]+$",
                "description": "Backend data endpoint, e.g. /api/session/current; never a frontend page URL, query string or fragment"}},
            "required": ["name", "method", "path"], "additionalProperties": False},
        "request": {"type": "object", "properties": {
            "params": {**JSON_SCHEMA, "description": "Schema of named route parameters, matching placeholders in signature.path"},
            "query": {**JSON_SCHEMA, "description": "Schema of query parameters"},
            "body": {**JSON_SCHEMA, "description": "Schema of the request body"},
            "headers": {**JSON_SCHEMA, "description": "Schema of request headers with lower-case names and explicit credential transport"}},
            "required": ["params", "query", "body", "headers"], "additionalProperties": False},
        "response": {"type": "object", "properties": {
            "success": {**HTTP_RESULT, "description": "Successful business response"},
            "errors": {"type": "array", "items": HTTP_RESULT, "description": "Requirement-supported rejection responses; [] when none"}},
            "required": ["success", "errors"], "additionalProperties": False},
        "precondition": {"type": "array", "description": "API assumptions with rejection status declared in response.errors", "items": {
            "type": "object", "properties": {"id": STRING, "description": STRING,
                "error_status": {"type": "integer", "description": "Status of the declared rejection response when this condition fails"}},
            "required": ["id", "description", "error_status"], "additionalProperties": False}},
        "postcondition": {"type": "array", "description": "Observable guarantees associated with declared response statuses", "items": {
            "type": "object", "properties": {"id": STRING, "description": STRING,
                "status": {"type": "integer", "description": "Declared response status to which this guarantee applies"}},
            "required": ["id", "description", "status"], "additionalProperties": False}}},
    "required": [*COMMON, "signature", "request", "response"], "additionalProperties": False}


def backend_tools() -> list[dict]:
    tools = []
    for kind, definition in (("api", API), ("module", MODULE)):
        for action in ("create", "update"):
            tools.append({"type": "function", "function": {"name": f"{action}_{kind}",
                "description": (f"Create a new canonical {kind}; fail if the ID already exists." if action == "create" else
                    f"Replace the complete contract of an existing {kind}; preserve earlier requirements. This is not a partial patch."),
                "parameters": {"type": "object", "properties": {
                    "id": {"type": "string", "description": f"Stable {kind} identity used in associations and calls; distinct from the implementation function name"},
                    "definition": definition},
                    "required": ["id", "definition"], "additionalProperties": False}}})
    tools.append({"type": "function", "function": {"name": "associate_requirement",
        "description": "Associate reused/new API and module entry points with the current requirement; validated after all mutations execute",
        "parameters": {"type": "object", "properties": {
            "api_ids": {**STRINGS, "description": "API entry-point IDs needed by the current requirement; [] if no HTTP exposure is needed"},
            "module_ids": {**STRINGS, "description": "Internal module root IDs needed by the requirement; transitive callees need not be repeated; [] when none"},
            "conventions": {"type": "object", "additionalProperties": STRING,
                "description": "Optional new or deliberately revised shared decisions, mapping stable IDs to normative descriptions; omit unchanged decisions"}},
            "required": ["api_ids", "module_ids"], "additionalProperties": False}}})
    return tools


def format_contracts(records: dict, kind: str) -> str:
    paragraphs = []
    for identity, record in records.items():
        paragraphs.append(f"{identity} — {record['description']}\n"
            f"Read: {', '.join(record['read']) or '(none)'}\n"
            f"Write: {', '.join(record['write']) or '(none)'}\n"
            f"Callers: {', '.join(record['callers']) or '(none)'}\n"
            f"Callees: {', '.join(record['callees']) or '(none)'}")
        keys = ("signature", "request", "response") if kind == "api" else ("name", "input", "output", "direct_read", "direct_write")
        for key in (*keys, "precondition", "postcondition"):
            paragraphs.append(key + ": " + json.dumps(record[key], ensure_ascii=False))
    return "\n\n".join(paragraphs) or "(none)"


class BackendDesignAgent(BaseAgent):
    def build_system_prompt(self) -> str:
        instructions = """You are an architecture designer incrementally designing the backend for ONE
requirement, preserving earlier accepted contracts. Design both HTTP APIs and reusable
internal modules between API and database. Produce contracts, not implementation code.

APPLICATION BOUNDARY
The generated frontend renders pages. Page URLs such as /, /register and /login are
frontend routes, NOT backend HTTP API paths. Design data endpoints under /api/.
For example, opening / to restore the username needs GET /api/session/current returning
JSON; do not design GET / serving rendered HTML. APIs return business data and action
outcomes, while UI labels, link visibility, page layout and rendering belong to frontend.
Do not create an HTML-rendering API or incidental UI formatting modules to implement a
page requirement. A requirement about a page is not permission to move rendering server-side.

Design API interfaces around data and actions needed by frontend scenarios.
Keep credential transport consistent and never expose stored password hashes or session
secrets in business response bodies. Describe only requirement-supported success and
rejection branches. Preconditions and postconditions must connect interface behavior
to observable outcomes, including unchanged data on rejection where required.

Modules perform computation, persistence, composition or shared business operations.
Describe each module's input assumptions, failure outcomes,
computed results and DB guarantees. Pure calculations have empty DB effects. Create
modules only for meaningful responsibilities; avoid splitting every statement or
introducing wrappers with no independent purpose. Module postconditions should explain
which output/failure branches its callers must handle; APIs map these to HTTP responses.
An internal requirement can associate modules without any HTTP API.

OBLIGATION AND CALL GRAPH
read/write contain TOTAL possible persistent effects across specified branches.
Modules additionally declare direct_read/direct_write for fields directly accessed
by their own logic. A module's total read/write MUST equal the union of direct effects
and all callees' total effects. APIs access the database through modules; their total
effects MUST equal the union of their callees. Module callees can only name modules;
cycles and calls back into APIs are forbidden. List each direct callee once; descriptions
and P/Q explain call order, parameter mapping, result composition and failure handling.
The compiler DERIVES callers as the inverse of callees for both API and module records;
do not supply callers in tool arguments. Forward references are allowed while staging;
all references must resolve when associate_requirement finalizes the design.

The current requirement's associated API/module totals must cover its read obligation
and have EXACTLY its write obligation. Supporting reads are allowed. This also covers
each step, and shared updates must preserve all earlier requirement coverage. Given
setup is not the current action. Keep rejection paths write-free when required; totals
still include successful-branch writes. Reload/reopening needs persisted read operations;
a create response cannot replace them. Do not inherit unrelated parent/reference effects.

REUSE AND RETRIEVAL
Supplied candidates combine BM25 and same-mode read/write overlap retrieval. They can
be reused, extended, or used as examples for distinct operations. Overlap is evidence
of data relevance, NOT proof of compatible behavior, inputs, security rules or outputs.
Never reuse a broad mutating operation that introduces unrelated writes. Pure modules
can be retrieved lexically even with empty effects. Complete callee dependencies are
included, along with connected callers needed to coordinate shared updates. No retrieve
tool is available. Stable canonical IDs preserve shared behavior.
Selected shared conventions must remain consistent across new and reused operations.

TOOLS
Use create_api/create_module for new contracts, update_api/update_module for deliberate
revisions preserving all previously required behavior. Use associate_requirement to
associate the required API entry points and internal module roots. Unchanged reuse needs ONLY this call. Include
internal roots when no HTTP entry exists; no need to list every transitive callee.
Optional conventions maps stable IDs to concise cross-operation decisions (cookie names,
identity representation, etc.); retain existing decisions unless explicitly corrected.

In the FIRST response, design the ENTIRE backend for this requirement at once.
Return ALL needed create_api/create_module/update_api/update_module calls together
with ONE associate_requirement call in the same tool_calls array. Do not intentionally
split normal design across rounds or wait for individual creation results. The tools
are executed before association validation, so their order in the response does not
matter and references to other records in the response are allowed. Reuse unchanged
records by association only. Use empty association lists if no backend work is needed.

Later rounds are ONLY for correcting errors in that initial complete design.
Successful create/update operations remain STAGED even when another tool or final
validation fails. Do not repeat successful creates. Retry failed creates, update
records whose contracts are wrong, and supply any missing operations. The latest
valid association arguments are retained; resubmit association only when missing or
incorrect. One canonical ID may be mutated once per response. Each tool receives its
own result; overall validation errors explain graph/coverage corrections. A fully
valid design ends immediately, without another model call. At most five model rounds
include the initial batch and corrections. Never serialize tool calls as assistant text.
"""
        return instructions

    def build_user_prompt(self, input: dict) -> str:
        requirement = input["requirement"]
        paragraphs = ["Design reusable backend APIs and modules for this requirement.",
            f"Current requirement: {requirement['id']} — {requirement['name']}\n"
            f"Parent module: {requirement.get('parent_module') or '(none)'}\nDescription:\n{requirement['description']}"]
        lines = []
        previous = None
        for step in requirement["steps"]:
            scenario = step["scenario"]
            if scenario["id"] != previous:
                lines.append(f"Scenario {scenario['id']}: {scenario['name']}")
                previous = scenario["id"]
            lines.append(f"Step {step['id']}")
            for key in ("Given", "When", "Then"):
                lines.append(f"{key}: {step[key]}")
            effects = input["step_obligations"][step["id"]]
            lines.append(f"DB read: {', '.join(effects['read']) or '(none)'}; DB write: {', '.join(effects['write']) or '(none)'}")
        paragraphs.append("Scenarios, actions and step obligations:\n" + ("\n".join(lines) or "(none)"))
        required = input["obligations"]["requirements"][requirement["id"]]
        paragraphs.append(f"Requirement obligations:\nRead: {', '.join(required['read']) or '(none)'}\n"
            f"Write: {', '.join(required['write']) or '(none)'}")
        paragraphs.append("Related database definitions:\n" + (format_schema(input["related_schema"]) or "(none)"))
        paragraphs.append("Related APIs from lexical/obligation retrieval:\n" + format_contracts(input["retrieved"]["apis"], "api"))
        paragraphs.append("Related modules and complete callee dependencies:\n" + format_contracts(input["retrieved"]["modules"], "module"))
        conventions = []
        for identity, description in input["selected_conventions"].items():
            conventions.append(f"- {identity}: {description}")
        paragraphs.append("Relevant shared decisions:\n" + ("\n".join(conventions) or "(none)"))
        paragraphs.append("In your first response, return every required API/module creation or update "
            "and one associate_requirement call together. Later responses are reserved for error corrections.")
        return "\n\n".join(paragraphs)

    def run(self, input: dict, max_rounds: int = 5) -> dict:
        if not 1 <= max_rounds <= 5:
            raise ValueError("Backend design requires between 1 and 5 rounds")
        messages = [{"role": "system", "content": self.build_system_prompt()},
            {"role": "user", "content": self.build_user_prompt(input)}]
        self.messages = messages
        last_error = "No complete backend design batch received"
        rid = input["requirement"]["id"]
        tools = backend_tools()
        parameters_by_tool = {}
        for tool in tools:
            function = tool["function"]
            parameters_by_tool[function["name"]] = function["parameters"]
        working = deepcopy(input["design"])
        association = None
        conventions = input["conventions"]
        fields = set(input["obligations"]["requirements"][rid]["read"])
        fields.update(input["obligations"]["requirements"][rid]["write"])
        for round_number in range(1, max_rounds + 1):
            response = self.model._request(model=self.model.name, messages=messages,
                tools=tools, tool_choice="required", parallel_tool_calls=True,
                **reasoning_arguments(self.model.name, self.model.reasoning))
            if not response.choices:
                raise ValueError("Backend design model returned no choices")
            choice = response.choices[0]
            message = choice.message
            messages.append(message.model_dump(exclude_none=True))
            calls = message.tool_calls or []
            errors = []
            results = []
            mutated = set()
            association_count = 0
            for call in calls:
                try:
                    if choice.finish_reason == "length":
                        raise ValueError("Response truncated; return complete tool arguments")
                    name = call.function.name
                    arguments = json.loads(call.function.arguments)
                    if name not in parameters_by_tool or not isinstance(arguments, dict):
                        raise ValueError(f"Invalid backend tool call: {name}")
                    parameters = parameters_by_tool[name]
                    if set(arguments) - set(parameters["properties"]) or set(parameters["required"]) - set(arguments):
                        raise ValueError(f"Invalid arguments for {name}")
                    if name == "associate_requirement":
                        association_count += 1
                        if association_count > 1:
                            raise ValueError("Return only one associate_requirement call per response")
                        for key in ("api_ids", "module_ids"):
                            if not isinstance(arguments[key], list) or any(not isinstance(item, str) for item in arguments[key]):
                                raise ValueError(f"{key} must be an array of IDs")
                        revised = merge_conventions(input["conventions"], arguments, rid, fields)
                        association = deepcopy(arguments)
                        conventions = revised
                        result = {"status": "STAGED", "message": "Association retained; validate after all operations"}
                    else:
                        kind = "apis" if name.endswith("_api") else "modules"
                        identity = arguments["id"]
                        if not isinstance(identity, str) or not identity.strip():
                            raise ValueError("Contract ID must be a nonempty string")
                        if identity in mutated:
                            raise ValueError(f"Mutate an ID only once per response: {identity}")
                        exists = identity in working[kind]
                        if name.startswith("create_") and (identity in working["apis"] or identity in working["modules"]):
                            raise ValueError(f"ID already exists; reuse or update: {identity}")
                        if name.startswith("update_") and not exists:
                            raise ValueError(f"Cannot update unknown ID: {identity}")
                        if name.startswith("update_") and identity in input["design"][kind] and identity not in input["retrieved"][kind]:
                            raise ValueError(f"Cannot replace an unseen shared contract: {identity}")
                        definition = arguments["definition"]
                        contract_schema = parameters["properties"]["definition"]
                        if not isinstance(definition, dict):
                            raise ValueError("definition must be a complete contract object")
                        missing = set(contract_schema["required"]) - set(definition)
                        unexpected = set(definition) - set(contract_schema["properties"])
                        if missing or unexpected:
                            hint = " Module definition.name is a mandatory function name, separate from id." if kind == "modules" and "name" in missing else ""
                            raise ValueError(f"Invalid {identity} contract: missing {sorted(missing)}, unexpected {sorted(unexpected)}. "
                                f"Required definition keys: {contract_schema['required']}.{hint} Retry this failed operation with a complete definition.")
                        function_name = definition["name"] if kind == "modules" else definition["signature"]["name"]
                        if not isinstance(function_name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", function_name):
                            raise ValueError(f"{identity} needs a function name such as resolveCurrentUser, separate from its contract ID")
                        if kind == "apis":
                            validate_http_signature(identity, definition["signature"])
                        working[kind][identity] = deepcopy(definition)
                        mutated.add(identity)
                        result = {"status": "STAGED", "id": identity,
                            "message": "Operation retained; use update rather than repeating create"}
                except (ValueError, TypeError, KeyError, AttributeError, IndexError) as error:
                    result = {"status": "FAILED", "error": str(error)}
                    errors.append(str(error))
                results.append((call, result))
            if not calls:
                errors.append("Return native tool calls; the first response must contain the complete design")
            if association is None:
                errors.append("The complete initial design requires one associate_requirement call; previously staged operations remain available")
            # Validate after executing ALL calls, independent of response ordering.
            accepted = None
            if association is not None:
                candidate = deepcopy(working)
                candidate["requirements"][rid] = association["api_ids"]
                candidate["requirement_modules"][rid] = association["module_ids"]
                try:
                    validate_backend_design(candidate, input["schema"], input["obligations"], input["tree"])
                    accepted = candidate
                except (ValueError, TypeError, KeyError, AttributeError, IndexError) as error:
                    feedback = {"error": str(error)}
                    if hasattr(error, "feedback"):
                        feedback["details"] = error.feedback
                    errors.append("Design validation: " + json.dumps(feedback, ensure_ascii=False))
            for call, result in results:
                if accepted is not None and not errors:
                    result["status"] = "SUCCESS"
                messages.append({"role": "tool", "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False)})
                record_tool_execution(call.model_dump(exclude_none=True), result, logger=self.logger)
            if accepted is not None and not errors:
                return {"design": accepted, "conventions": conventions}
            last_error = "; ".join(errors)
            messages.append({"role": "user", "content":
                "Correct only failed or invalid operations. Successful STAGED operations and the latest "
                "association remain available; do not recreate them. Retry failed creates, use updates "
                "for retained contracts, and change association only if necessary. Errors: " + last_error})
        raise RuntimeError(f"Backend design exhausted {max_rounds} rounds: {last_error}")
