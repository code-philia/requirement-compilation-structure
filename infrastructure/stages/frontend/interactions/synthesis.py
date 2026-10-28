"""Step 11 design: retrieved UI/API context -> events -> typed event contracts.

Prompts describe trigger/event decomposition and Contract Inference. Validators
check obligation coverage and typed mappings before ui_interactions.json is
published. This module neither writes application code nor runs browser tests."""

import json

from infrastructure.stages.frontend.interactions.contracts import validate_contract
from infrastructure.stages.frontend.interactions.design import (InteractionCoverageError, apply_decomposition, empty_interactions,
    event_ids, relevant_pages, require_fields, text, validate_interactions)
from infrastructure.shared.rag.apis import ApiRetriever
from infrastructure.shared.rag.interactions import InteractionRetriever
from infrastructure.utils.files import save_json

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
Event keyed by ID: {"description":"...","read":[],"write":[],
"obligations":{"read":[],"write":[]},"actions":[]}.
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
Event obligations use DB Entity.field symbols, separately from frontend variables. They
must equal the union of called APIs' READ/WRITE sets. Local-only events have empty sets.
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


def propose(model, instructions, request, validate, console, label):
    """Request and validate at most three model proposals, passing each rejected proposal and error into the next attempt."""
    for attempt in range(1, 4):
        response = None
        console.show(f"{label} | Model proposal {attempt}/3", "Validate before accepting; rejected proposals do not change the shared design.")
        try:
            response = model.generate_json(instructions, request)
            return validate(response), response
        except ValueError as error:
            correction = {"error": str(error), "previous_response": response}
            if isinstance(error, InteractionCoverageError):
                correction["obligation_coverage"] = error.feedback
            if isinstance(error, json.JSONDecodeError):
                correction["invalid_response"] = error.doc
            console.show(f"{label} | Validation failed", json.dumps(correction, ensure_ascii=False, indent=2))
            if attempt == 3:
                raise ValueError(f"{label} failed after 3 proposals: {error}") from error
            request["correction"] = correction


def synthesize_interactions(arc_dir, ui, tree, schema, obligations, backend, contexts, model, console, top_k=6):
    """Design triggers/events per leaf, then infer contracts for each shared event.

    Retrieve existing page events and APIs, validate obligation-union coverage,
    and show correction feedback. Publish ui_interactions.json only after the
    complete decomposition and all event contracts validate."""
    result, analyzed = empty_interactions(tree), []
    retriever, api_retriever = InteractionRetriever(), ApiRetriever()
    for rid in tree.requirements:
        if tree.children[rid]:
            console.show(rid + " | Skip non-leaf interaction analysis", "Parents retain empty direct bindings. Only leaf interaction decompositions are checked.")
    for number, rid in enumerate(tree.leaves, 1):
        label = f"Interaction Decomposition {number}/{len(tree.leaves)} {rid}"
        pages = relevant_pages(ui, rid)
        console.show(label + " | 1. Requirement, steps and DB obligations", json.dumps({
            "requirement": contexts[rid], "obligations": obligations["requirements"][rid],
            "steps": {sid: obligations["steps"][sid] for sid in tree.own_steps[rid]}}, ensure_ascii=False, indent=2))
        console.show(label + " | 2. Relevant page subtrees and frontend data", json.dumps(pages, ensure_ascii=False, indent=2))
        console.show(label + " | 3. All Existing Events", json.dumps({eid: event["description"] for eid, event in result["events"].items()}, ensure_ascii=False, indent=2))
        retrieved = retriever.retrieve(contexts[rid], pages, result, top_k)
        ranked = api_retriever.retrieve(json.dumps(contexts[rid], ensure_ascii=False), backend["apis"], top_k)
        allowed = backend["requirements"][rid]
        # Direct allocations are always included, even without lexical matches.
        api_context = {aid: backend["apis"][aid] for aid in allowed}
        console.show(label + " | 4. Retrieved interactions and allocated APIs (RAG)", json.dumps({
            "interactions": retrieved, "api_matches": ranked["matches"], "allowed_apis": api_context}, ensure_ascii=False, indent=2))
        request = {"requirement": contexts[rid], "page_subtrees": pages,
            "page_inventory": {pid: {"name": page["name"], "route": page["route"]} for pid, page in ui["pages"].items()},
            "retrieved_interactions": retrieved, "event_inventory": {eid: event["description"] for eid, event in result["events"].items()},
            "allowed_api_ids": allowed, "backend_apis": api_context, "api_matches": ranked["matches"],
            "obligations": obligations["requirements"][rid],
            "step_obligations": {sid: obligations["steps"][sid] for sid in tree.own_steps[rid]},
            "step_ui": {sid: ui["steps"][sid] for sid in tree.own_steps[rid]}}
        result, response = propose(model, DECOMPOSE, request,
            lambda value: apply_decomposition(result, value, rid, retrieved, ui, tree, schema, obligations, backend, analyzed), console, label)
        analyzed.append(rid)
        console.show(label + " | 5. Accepted triggers/events and obligation union", json.dumps({
            "explanation": response["explanation"], "triggers": {tid: result["triggers"][tid] for tid in result["requirements"][rid]},
            "events": {eid: result["events"][eid] for eid in sorted(event_ids(result, result["requirements"][rid]))}}, ensure_ascii=False, indent=2))
    validate_interactions(result, ui, tree, schema, obligations, backend, analyzed, complete=True)
    for number, eid in enumerate(result["events"], 1):
        label = f"Interaction Contract Inference {number}/{len(result['events'])} {eid}"
        tids = [tid for tid, trigger in result["triggers"].items() if trigger["action"] == eid]
        uses = [rid for rid, bindings in result["requirements"].items() if set(tids).intersection(bindings)]
        request = {"event_id": eid, "event": result["events"][eid],
            "triggers": {tid: result["triggers"][tid] for tid in tids},
            "all_requirement_uses": [contexts[rid] for rid in uses],
            "step_uses": {sid: tree.steps[sid] for sid, bindings in result["steps"].items() if set(tids).intersection(bindings)},
            "frontend_data": {var: {"binding": ui["bindings"][var], "descriptor": next(data for node in ui["elements"].values() for data in node.get("data", []) if data["var"] == var)}
                for var in set(result["events"][eid]["read"]) | set(result["events"][eid]["write"]) | {var for tid in tids for var in result["triggers"][tid]["read"]}},
            "page_inventory": {pid: {"route": page["route"], "name": page["name"]} for pid, page in ui["pages"].items()},
            "backend_apis": {action["api"]: backend["apis"][action["api"]] for action in result["events"][eid]["actions"] if action["kind"] == "api"}}
        console.show(label + " | Event, shared uses and fixed backend contracts", json.dumps(request, ensure_ascii=False, indent=2))

        def accept(value):
            """Attach a proposed event contract to a copy and validate it against the accepted decomposition."""
            require_fields(value, {"contract", "explanation"}, "Contract inference response")
            text(value["explanation"], "explanation")
            validate_contract(eid, value["contract"], result, ui, backend)
            return value["contract"]

        contract, response = propose(model, CONTRACT, request, accept, console, label)
        result["contracts"][eid] = contract
        console.show(label + " | Validated P/Q and data mappings", json.dumps(response, ensure_ascii=False, indent=2))
    validate_interactions(result, ui, tree, schema, obligations, backend, analyzed, complete=True)
    if set(result["contracts"]) != set(result["events"]):
        raise ValueError("Every event needs exactly one canonical interaction contract")
    for eid, contract in result["contracts"].items():
        validate_contract(eid, contract, result, ui, backend)
    save_json(arc_dir / "ui_interactions.json", result)
    return result
