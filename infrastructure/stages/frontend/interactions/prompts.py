"""Stage 11 prompts, complete examples, and exact validation targets.

Example contexts define their own symbols and expected responses. They teach the
representation only; actual model proposals must use the current request's IDs.
"""

from copy import deepcopy
import json

from infrastructure.stages.frontend.interactions.contracts import required_request_pointers, request_schema, schema_at

DECOMPOSE = '''Design Trigger Primitives and their event workflows, not implementation code.
Use only existing UI nodes/data and canonical backend APIs. Analyze the CURRENT LEAF's
own behavior and steps. Parents are organizational; never copy child associations.
Return exactly {"triggers":{},"events":{},"requirement_triggers":[],"step_triggers":{},"explanation":"..."}.
Dictionary records are complete new/modified definitions. Omit unchanged reused records.
Preserve stable IDs and all previously accepted allocations. Reuse retrieved interactions
on the same page before adding duplicates. One source/interaction has one canonical trigger;
combine its success/error behavior inside the event. Several leaves may use that trigger.
Trigger keyed by ID: {"source":"UI-ID","event":"submit","guard":null,
"read":["registration.username"],"action":"EVENT-ID","write":["registration.errorVisible"]}.
Interaction kinds: click,change,input,submit,keydown,keyup,mount. mount can use a page root
from its retrieved subtree even if that root is not a direct requirement UI association.
Use a canonical page root for mount and a form for native submit; buttons use click.
guard is null or a nonempty English enabling rule. read covers guard and event inputs;
write exactly summarizes event frontend writes. No executable expressions/code.
Event keyed by ID: {"description":"...","read":[],"write":[],"actions":[]}.
Actions are ordered, with unique IDs scoped to this event. Every action has exactly
id,kind,description,when,read,write; api actions additionally have api; navigate actions
additionally have page. kind is local,api,navigate. when is null or an English branch
condition. read/write refer to FRONTEND variables. Only local actions update frontend
variables; API and navigate actions have write=[]. Use explicit local actions to map
responses/errors after an API call. Event read/write are the UNION of action read/write.
Response-dependent local/navigation actions need when text naming the exact EARLIER
API action ID and numeric status, for example "CALL_REGISTER returned 201". Split
different status branches into distinct actions, and state extra body conditions for
same-status alternatives such as authenticated=true versus authenticated=false.
Use local actions for input/change updates and validation. Each directly associated
editable UI control with data needs an input/change trigger writing its frontend var.
Native input values are trigger inputs, not invented frontend variables. Include local
error handling and ordinary navigation with empty DB obligations. Do not invent loading
or intermediate state variables missing from the UI design; use existing variables and
semantic conditions. Missing essential UI data requires revisiting step 09, not fabrication.
Event database obligations are compiler-derived from the APIs in its actions. Do not
return, copy, or reason about an obligations field in the proposal. The compiler adds
the final DB Entity.field read/write union; local-only events receive empty sets.
Call ONLY allowed_api_ids allocated directly to this leaf. Cover every allocated API
with an event call, including APIs with empty DB effects. Existing page lifecycle events
owned by another requirement continue to run globally; do not claim them as a direct
current-leaf operation when its upstream API allocation does not include them.
The event DB obligation union must cover this leaf and stay within its declared DB
obligations. Every supplied step needs a trigger list (possibly [] for backend-only
steps). Step triggers are a subset of this leaf's triggers and their DB union covers the
step obligations. A rejection step can reference the same submit event as success: the
API's possible writes are not a claim that rejection writes; contracts describe that branch.
Cover local UI steps even if their DB obligations are empty. Include lifecycle/session
resolution when directly required. Navigation can target any existing page, but do not
invent new pages. All source/data references must belong to the retrieved page subtrees.
Later Contract Inference will supply typed request/update mappings and P/Q; omit them now.
On correction, return the entire corrected proposal relative to the unchanged accepted
registry, including new records from the previous rejected proposal. Return one JSON object.
'''

CONTRACT = '''Infer a canonical interaction contract for this event using ALL supplied
requirement/step/trigger uses. Keep triggers, actions, frontend/DB obligations and backend
contracts fixed. Return exactly {"contract":{"precondition":[],"postcondition":[],"actions":{}},"explanation":"..."}.
P record: {"id":"P-1","description":"English condition","read":["frontend.var"]}.
Q record: {"id":"Q-1","description":"English observable outcome","actions":["ACTION-ID"],
"write":["frontend.var"],"outcome":null,"api_conditions":[],"page":null}.
Use unique P-/Q- IDs within this event. P can be empty. Q covers every event action and
frontend write. For each API outcome, set outcome={"call":"API-ACTION-ID","status":200}
and api_conditions to relevant upstream Q IDs for that API/status. Reference the API
action in actions, plus relevant local/navigation actions. Cover EVERY response status
and upstream API postcondition, including successful responses with different meanings.
Use page only for a Q with a matching navigation action. Describe forbidden DB writes
on rejection and existing records preserved, not just HTTP status or a displayed message.
Action contracts are keyed by the fixed ordered action IDs:
- local: {"updates":{"frontend.var":EXPR},"assertions":["English semantic validation rule"]}.
  updates keys equal action.write. Empty updates is valid for validation-only local actions.
- api: {"request":{"/body/username":EXPR},"credentials":"same-origin"}.
  Request keys are declared JSON Pointers under params/query/body/headers. Map all
  required request fields, omitting empty sections. Do not map both an object and its
  descendants. credentials is same-origin,include,omit. Browser-managed cookie headers
  use only {"source":"transport","name":"cookie"} at /headers/cookie with credentials.
  Do not expose HttpOnly cookies or read Set-Cookie from JavaScript. Transport effects
  remain browser responsibilities and can be described in Q.
- navigate: {}. The target page is already fixed in the action.
EXPR is a JSON record, never executable code:
  {"source":"data","var":"existing.frontend.var"}
  {"source":"literal","value":JSON_VALUE}
  {"source":"input","field":"value"} (string), or checked (boolean), or key (string)
  {"source":"response","call":"EARLIER-API-ACTION","status":200,"field":"/body/username"}
  {"source":"transform","operation":"English transformation","inputs":[EXPR],"dtype":"string"}
Dtypes: string,integer,number,boolean,array,object,null. Native input value/checked applies
to input/change triggers; key applies to keydown/keyup. A numeric input value needs an
explicit conversion from its native string. Map UI data to exact API field names without
inventing normalization. Preserve confirm_password when the canonical API requires it;
UI-only data without a request field stays local. Never fabricate a source to satisfy a
missing required request field, or hardcode sample credentials instead of using inputs.
Expressions may read only action.read. API results must come from EARLIER calls. Any action
using a response expression needs when text containing the exact call ID and numeric
status, plus relevant semantic conditions for optional fields or same-status branches.
Semantic transforms and validation descriptions are not formal proofs: state the required
behavior clearly for later implementation/E2E tests. Align request validity/guards with
backend P; do not claim the client can prove server-only checks such as username uniqueness.
If the fixed decomposition cannot support a valid contract, report the precise mismatch
rather than altering its actions or inventing UI variables. On correction, return one
complete corrected contract. Use English descriptions and the existing symbols/IDs.
'''


def example_shape(properties):
    """Build an inline object schema used only in the self-contained prompt examples."""
    return {"type": "object", "properties": properties, "required": list(properties)}


def example_api(name, method, path, reads, writes, body, branches):
    """Construct a canonical sample API including exact response-status postcondition IDs."""
    responses, conditions = [], []
    for status, fields, meanings in branches:
        responses.append({"status": status, "body": example_shape(fields), "headers": example_shape({})})
        conditions.extend({"id": qid, "description": description,
            "response_fields": ["/body/" + next(iter(fields))], "status": status}
            for qid, description in meanings)
    return {"description": name, "read": reads, "write": writes,
        "signature": {"name": name, "method": method, "path": path},
        "request": {section: example_shape(body if section == "body" else {})
            for section in ("params", "query", "body", "headers")},
        "response": {"success": responses[0], "errors": responses[1:]},
        "precondition": [], "postcondition": conditions}


def example_ui():
    """Provide a small fixed UI/data world shared by the examples, independent of real input."""
    variables = {"form.username": ("UI-username", "string", ""), "form.error": ("UI-error", "string", ""),
        "home.authenticated": ("UI-home", "boolean", False), "home.username": ("UI-home", "string", "")}
    elements = {}
    for uid, kind, parent in (("UI-home", "page", None), ("UI-register", "page", None),
            ("UI-username", "input", "UI-register"), ("UI-error", "alert", "UI-register"),
            ("UI-submit", "button", "UI-register"), ("UI-register-link", "button", "UI-home")):
        elements[uid] = {"type": kind, "parent": parent,
            "mode": ["user_write"] if kind == "input" else [], "data": [], "prop": {}}
    bindings = {}
    for var, (uid, dtype, initial) in variables.items():
        elements[uid]["data"].append({"var": var, "dtype": dtype, "constraints": []})
        bindings[var] = {"owner": "UI-home" if var.startswith("home.") else "UI-register",
            "initial": initial, "source": "Example local UI state"}
    return {"pages": {"home": {"name": "Home", "route": "/", "root": "UI-home", "images": [], "fixtures": {"default": {}}},
            "registration": {"name": "Registration", "route": "/register", "root": "UI-register", "images": [], "fixtures": {"default": {}}}},
        "elements": elements, "bindings": bindings, "requirements": {}, "steps": {}, "triggers": {}, "events": {}}


def action(identity, kind, description, *, when=None, read=(), write=(), **extra):
    """Create one complete fixed action for an example event."""
    return {"id": identity, "kind": kind, "description": description, "when": when,
        "read": list(read), "write": list(write), **extra}


def condition(identity, description, actions, *, write=(), call=None, status=None, api_conditions=(), page=None):
    """Create a complete example Q, retaining required empty lists and null fields."""
    return {"id": identity, "description": description, "actions": actions, "write": list(write),
        "outcome": None if call is None else {"call": call, "status": status},
        "api_conditions": list(api_conditions), "page": page}


def example_case(identity, title, source, interaction, actions, action_contracts, postconditions, *, apis=None, preconditions=None):
    """Bundle fixed input context and a complete valid contract response for one example."""
    apis = apis or {}
    reads = sorted({var for item in actions for var in item["read"]})
    writes = sorted({var for item in actions for var in item["write"]})
    event = {"description": title, "read": reads, "write": writes,
        "obligations": {mode: sorted({symbol for api in apis.values() for symbol in api[mode]}) for mode in ("read", "write")},
        "actions": actions}
    trigger = {"source": source, "event": interaction, "guard": None, "read": reads, "write": writes, "action": identity}
    return {"title": title, "event_id": identity, "event": event, "triggers": {"TR-" + identity: trigger},
        "ui": example_ui(), "backend": {"apis": apis}, "response": {
            "contract": {"precondition": preconditions or [], "postcondition": postconditions, "actions": action_contracts},
            "explanation": title + "; use the exact fixed action IDs and upstream API Q IDs."}}


def build_examples():
    """Build input, navigation, session-branch, and API success/rejection examples."""
    input_case = example_case("EVT-USERNAME", "Update a username from a native input", "UI-username", "input",
        [action("SET_USERNAME", "local", "Store the current native input value", write=["form.username"])],
        {"SET_USERNAME": {"updates": {"form.username": {"source": "input", "field": "value"}}, "assertions": []}},
        [condition("Q-INPUT", "The username equals the native input value; no database writes occur.", ["SET_USERNAME"], write=["form.username"])])
    navigation = example_case("EVT-OPEN-REGISTER", "Navigate to the existing registration page", "UI-register-link", "click",
        [action("OPEN_REGISTER", "navigate", "Open registration", page="registration")], {"OPEN_REGISTER": {}},
        [condition("Q-NAVIGATE", "The registration page is displayed.", ["OPEN_REGISTER"], page="registration")])
    session_api = example_api("getSession", "GET", "/api/session", ["Account.username", "Session.id"], [], {}, [
        (200, {"authenticated": {"type": "boolean"}, "username": {"type": "string"}}, [
            ("Q-SESSION-AUTHENTICATED", "A valid session returns authenticated=true and its username."),
            ("Q-SESSION-ANONYMOUS", "An absent or invalid session returns authenticated=false and an empty username.")])])
    # Cookie transport is optional and browser-managed, not a frontend state variable.
    session_api["request"]["headers"] = {"type": "object", "properties": {"cookie": {"type": "string"}}, "required": []}
    session_writes = ["home.authenticated", "home.username"]
    session = example_case("EVT-SESSION", "Resolve both session outcomes sharing HTTP 200", "UI-home", "mount", [
        action("CALL_SESSION", "api", "Resolve the browser session", api="API-SESSION"),
        action("SHOW_USER", "local", "Display the authenticated user", when="CALL_SESSION returned 200 and authenticated is true", write=session_writes),
        action("SHOW_GUEST", "local", "Display the signed-out state", when="CALL_SESSION returned 200 and authenticated is false", write=session_writes),
    ], {"CALL_SESSION": {"request": {"/headers/cookie": {"source": "transport", "name": "cookie"}}, "credentials": "same-origin"},
        "SHOW_USER": {"updates": {"home.authenticated": {"source": "response", "call": "CALL_SESSION", "status": 200, "field": "/body/authenticated"},
            "home.username": {"source": "response", "call": "CALL_SESSION", "status": 200, "field": "/body/username"}}, "assertions": []},
        "SHOW_GUEST": {"updates": {"home.authenticated": {"source": "literal", "value": False},
            "home.username": {"source": "literal", "value": ""}}, "assertions": []}}, [
        condition("Q-AUTHENTICATED", "A valid session displays the returned user without database writes.", ["CALL_SESSION", "SHOW_USER"],
            write=session_writes, call="CALL_SESSION", status=200, api_conditions=["Q-SESSION-AUTHENTICATED"]),
        condition("Q-ANONYMOUS", "No valid session displays the signed-out state without database writes.", ["CALL_SESSION", "SHOW_GUEST"],
            write=session_writes, call="CALL_SESSION", status=200, api_conditions=["Q-SESSION-ANONYMOUS"]),
    ], apis={"API-SESSION": session_api})
    register_api = example_api("registerUser", "POST", "/api/register", ["Account.username"], ["Account.id", "Account.username"],
        {"username": {"type": "string", "minLength": 1}}, [
            (201, {"username": {"type": "string"}}, [("Q-REGISTER-CREATED", "Create the account and return its username.")]),
            (409, {"error": {"type": "string"}}, [("Q-REGISTER-DUPLICATE", "Reject a duplicate username; create no account and preserve existing records.")]),
        ])
    submit = example_case("EVT-REGISTER", "Submit with success navigation and duplicate rejection", "UI-submit", "click", [
        action("VALIDATE_USERNAME", "local", "Check the username before submission", read=["form.username"]),
        action("CALL_REGISTER", "api", "Register the username", read=["form.username"], api="API-REGISTER"),
        action("CLEAR_ERROR", "local", "Clear the displayed error", when="CALL_REGISTER returned 201", write=["form.error"]),
        action("OPEN_HOME", "navigate", "Return to the home page", when="CALL_REGISTER returned 201", page="home"),
        action("SHOW_ERROR", "local", "Show the duplicate error", when="CALL_REGISTER returned 409", write=["form.error"]),
    ], {"VALIDATE_USERNAME": {"updates": {}, "assertions": ["Submit only when the username is nonempty; uniqueness is checked by the server."]},
        "CALL_REGISTER": {"request": {"/body/username": {"source": "data", "var": "form.username"}}, "credentials": "same-origin"},
        "CLEAR_ERROR": {"updates": {"form.error": {"source": "literal", "value": ""}}, "assertions": []}, "OPEN_HOME": {},
        "SHOW_ERROR": {"updates": {"form.error": {"source": "response", "call": "CALL_REGISTER", "status": 409, "field": "/body/error"}}, "assertions": []}}, [
        condition("Q-VALIDATE", "The username is checked locally before calling the API.", ["VALIDATE_USERNAME"]),
        condition("Q-CREATED", "Successful registration clears errors and opens home.", ["CALL_REGISTER", "CLEAR_ERROR", "OPEN_HOME"],
            write=["form.error"], call="CALL_REGISTER", status=201, api_conditions=["Q-REGISTER-CREATED"], page="home"),
        condition("Q-DUPLICATE", "Duplicate registration shows an error, creates no account, and preserves existing records.", ["CALL_REGISTER", "SHOW_ERROR"],
            write=["form.error"], call="CALL_REGISTER", status=409, api_conditions=["Q-REGISTER-DUPLICATE"]),
    ], apis={"API-REGISTER": register_api}, preconditions=[{"id": "P-USERNAME", "description": "The username is nonempty before submission.", "read": ["form.username"]}])
    return {"input": input_case, "navigation": navigation, "session": session, "submit": submit}


EXAMPLES = build_examples()


def example_context(case):
    """Show the fixed inputs needed to understand a complete contract example."""
    variables = set(case["event"]["read"]) | set(case["event"]["write"])
    return {"event_id": case["event_id"], "event": case["event"], "triggers": case["triggers"],
        "frontend_data": {var: {"binding": case["ui"]["bindings"][var],
            "descriptor": next(data for node in case["ui"]["elements"].values() for data in node["data"] if data["var"] == var)} for var in sorted(variables)},
        "page_inventory": {pid: {"route": page["route"], "name": page["name"]} for pid, page in case["ui"]["pages"].items()},
        "backend_apis": case["backend"]["apis"]}


def contract_prompt(event):
    """Append complete examples relevant to the current action kinds, avoiding unrelated prompt volume."""
    kinds = {item["kind"] for item in event["actions"]}
    selected = ["session", "submit"] if "api" in kinds else ["navigation"] if kinds == {"navigate"} else ["input", "navigation"] if "navigate" in kinds else ["input"]
    examples = "\n\n".join(f"Example: {EXAMPLES[key]['title']}\nGiven input:\n"
        + json.dumps(example_context(EXAMPLES[key]), indent=2)
        + "\nComplete response:\n" + json.dumps(EXAMPLES[key]["response"], indent=2) for key in selected)
    return CONTRACT + '''

Q records are OBJECTS, never plain strings. Include all seven Q fields, even when
write/api_conditions are [] and outcome/page are null. Local-only Q uses outcome=null
and api_conditions=[]. A navigation action contract is {}, but still needs a Q.
Use validation_targets for the actual required mappings and outcomes. api_conditions
contains BACKEND API postcondition IDs, not UI Q IDs, API IDs, or P IDs. A single
status can have several backend Q IDs: trace all of them with meaningful branches.
A response expression's call is the earlier ACTION ID, never the API ID. Its status
is an integer and field is a JSON Pointer such as /body/username. Each dependent
fixed action.when must name that call ID and numeric status.
These examples are independent format examples, not additional requirements. Replace
all sample names, fields, statuses, and IDs with the CURRENT request's exact values.
Do not add example actions or variables to the fixed current event.
''' + examples


def contract_targets(eid, interactions, backend):
    """List exact action/write, request-pointer, and upstream-Q coverage targets from accepted inputs."""
    event = interactions["events"][eid]
    actions, outcomes = {}, []
    for item in event["actions"]:
        aid = item["id"]
        target = {"kind": item["kind"], "allowed_data_reads": item["read"]}
        if item["kind"] == "local":
            target["required_update_variables"] = item["write"]
        elif item["kind"] == "navigate":
            target["page"] = item["page"]
        else:
            api = backend["apis"][item["api"]]
            root = request_schema(api)
            target["required_request_fields"] = {pointer: schema_at(root, pointer)["type"] for pointer in required_request_pointers(api)}
            for branch in [api["response"]["success"], *api["response"]["errors"]]:
                outcomes.append({"call": aid, "status": branch["status"],
                    "api_conditions": [condition["id"] for condition in api["postcondition"] if condition["status"] == branch["status"]]})
        actions[aid] = target
    return {"action_contracts": actions, "postconditions": {"required_action_references": list(actions),
        "required_frontend_writes": event["write"], "required_api_outcomes": outcomes}}


def decomposition_example(case, include_input=False):
    """Pair a complete decomposition proposal with its fixed UI/API/step context."""
    cases = [EXAMPLES["input"], case] if include_input else [case]
    triggers = {tid: deepcopy(trigger) for item in cases for tid, trigger in item["triggers"].items()}
    events = {item["event_id"]: deepcopy(item["event"]) for item in cases}
    for event in events.values():
        event.pop("obligations", None)
    steps = {f"STEP-EXAMPLE-{number}": list(item["triggers"]) for number, item in enumerate(cases, 1)}
    variables = set().union(*(set(item["event"]["read"]) | set(item["event"]["write"]) for item in cases))
    return {"given": {
        "current_leaf": "REQ-EXAMPLE", "own_step_ids": list(steps),
        "ui_elements": {uid: node for uid, node in case["ui"]["elements"].items()
            if uid.startswith("UI-register") or uid in {"UI-username", "UI-error", "UI-submit"}},
        "frontend_bindings": {var: case["ui"]["bindings"][var] for var in sorted(variables)},
        "existing_pages": {pid: {"route": page["route"], "root": page["root"]} for pid, page in case["ui"]["pages"].items()},
        "allowed_api_ids": list(case["backend"]["apis"]), "backend_apis": case["backend"]["apis"],
        "obligations": case["event"]["obligations"],
        "step_obligations": {sid: item["event"]["obligations"] for sid, item in zip(steps, cases)},
    }, "response": {"triggers": triggers, "events": events, "requirement_triggers": list(triggers),
        "step_triggers": steps, "explanation": "Use only existing UI/data/APIs; allocate frontend and database effects separately."}}


DECOMPOSITION_EXAMPLES = [decomposition_example(EXAMPLES["input"]), decomposition_example(EXAMPLES["submit"], include_input=True)]
DECOMPOSE += '''

The following are COMPLETE, independent format examples. All UI elements, variables,
and APIs in them already exist before interaction design. Substitute the CURRENT
request's exact IDs, fields, statuses, allocated APIs, and own step IDs. Do not copy
example business features into the current requirement. Frontend variable names and
DB Entity.field symbols belong to separate sets. Local-only input events have empty
DB sets, even when their frontend write set is nonempty.
''' + "\n\n".join("Example input:\n" + json.dumps(item["given"], indent=2)
    + "\nComplete decomposition response:\n" + json.dumps(item["response"], indent=2) for item in DECOMPOSITION_EXAMPLES)
DECOMPOSE += '''

If retrieved triggers/events already suffice, use triggers={} and events={}, but
still return requirement_triggers and step_triggers with the reused IDs. If a record
must change, return its complete new definition, preserving its identity and prior
allocations. No UI elements, data variables, or backend APIs may be invented here.
'''
