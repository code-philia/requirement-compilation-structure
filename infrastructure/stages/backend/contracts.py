"""Validate API-level bindings to shared permission, feature and workflow contracts."""

# Infrastructure effects remain observable postconditions, but handlers cannot
# write these compiler-owned tables and do not charge their fields as domain R/W.
PLATFORM_EFFECT_TABLES = {"workflow_audit", "command_receipts"}


def domain_effect_fields(transition):
    return {f for effect in transition["effects"] for f in effect["fields"]
        if f.split('.')[0] not in PLATFORM_EFFECT_TABLES}

CONTRACT_INSTRUCTIONS = '''
SHARED BACKEND CONTRACTS
backend_foundation is the canonical reviewed security/workflow plan, not a suggestion.
Every new or changed API must include:
"security":{"mode":"policy|session","permissions":[{"resource":"catalog-id","action":"catalog-action"}],"features":["feature-id"],"record_id":"params.id or body.id or null","resource":"primary resource or null","action":"primary catalog action or null","operation":"read|create|update|delete|command|bulk"},
"process_refs":["source-process-id"],
"workflow": null OR {"machine":"MACHINE-ID","transition":"TRANSITION-ID","record_id":"params.id","guard_bindings":{"G-ID":"P-ID"},"effect_bindings":{"E-ID":"Q-ID"},"related_transitions":[]}
Use Express colon path parameters, e.g. /api/orders/:id/approve, and one canonical
method/path per operation. GET requests cannot mutate persisted data.
Use mode=policy for all business resource access, including lists, reports, exports,
printing, imports and nested/related records. mode=session is only for authenticated
operations with no catalog business resource.
Record ownership/scope checks run BEFORE the handler and default to HTTP 403, including
unknown ownership metadata. For a source/contract requiring nondisclosing HTTP 404, set
security.record_denial_status=404; missing and forbidden records then share a generic
404 message. Only 403/404 are supported, and operation-level permission failures remain
403. Keep precondition/error branches consistent; handlers cannot intercept these checks.
Public login/session endpoints are fixed at POST /api/auth/login, GET /api/auth/me,
POST /api/auth/logout; do not redefine them.
Reuse supplied platform API IDs unchanged; they already cover their infrastructure DB effects.
The platform provides account/password auth only, persistent opaque sessions/CSRF, admin
full permissions, Casbin domain policies, and normalized data boundaries. Never accept
role/unit/owner/assignee identity claims from request bodies or headers.

Select exact canonical permissions/features; do not grant missing permissions in a handler.
Effective supplements require foundation-level source-cited decisions. Lists/aggregates
must use request.access.scope(resource,action,'alias.id') in EVERY contributing query,
including counts, joins, lookups, export and print. New records and every created side-effect
record can call request.access.register(resource,id); the gateway also registers detected
created rows in the trusted current unit/owner. An explicit workflow assignment effect may
call request.access.assign(resource,id,assigneeId,requiredRole); it validates persisted unit
membership and role. Include record_access.assignee_id in that effect/write contract.
Records without ownership metadata are denied to ordinary users. Metadata is infrastructure,
not extra business effect obligations. Follow related-record domain checks; never trust
unvalidated foreign IDs.

When changing a canonical machine's state, bind exactly one existing transition. The
platform checks current state before the handler, applies the transition with XState and
optimistic state comparison after successful effects, and commits state/effects/audit in
one transaction. A failed response rolls back writes. Workflow APIs require Idempotency-Key;
replays return the original response without executing effects again. Bind every machine
guard to a P ID and every effect to a Q ID; cover their actual fields in read/write sets.
For compiler-owned workflow_audit/command_receipts effects, retain the Q binding and
verify the committed platform outcome, but omit those automatic fields from handler
write obligations. Business stock/ledger fields and explicit assignee writes remain
domain obligations. Never write the automatic audit/receipt tables in a handler.
Use operation=bulk for unit-wide operations such as imports or reset without a single
record selector; declare their exact primary action and permissions. Bulk mutations also
require Idempotency-Key. Data reset must preserve protected identity/organization data.
The handler receives a parameterized data-SQL facade (prepare/get/all/run); exec, pragma,
DDL, transaction and connection lifecycle APIs are unavailable.
For a compound command, workflow.related_transitions may list additional canonical
{machine,transition,guard_bindings,effect_bindings} bindings. Execute those only through
await request.access.advance(machine,transition,recordId), after creating child records
in their initial state. This keeps child transitions/audit within the primary transaction.
Every related transition requires its declared resource/action permission; no arbitrary
second machine or undeclared state writes are allowed.
The handler implements non-state business guards/effects; it MUST NOT independently commit,
start a transaction, write machine state, or apply the transition a second time. For creates,
initialize machine state to its declared initial value; subsequent state writes require a
transition. Describe failure paths and original-movement compensation explicitly.

No domain is privileged by its name: derive commands, roles, entities and transitions from
this bundle. Preserve general CRUD, search, paging, settings, files, reports and other source
features in the same design process. Use installed decimal.js for ER decimal-text arithmetic and aggregation; honor source rounding
rules and return the required representation. Do not coerce monetary/quantity strings to JS
Number or rely on SQLite floating-point SUM for exact arithmetic.
The supplied evidence/decisions must reach implementation,
rejected-proposal feedback and repairs, not merely this first design call.
'''


def validate_backend_contracts(design, foundation, evidence, schema):
    if not foundation.get("enabled"):
        return
    catalog = evidence["authorization"]["catalog"]
    resources = {row["id"] for row in catalog["resources"]}
    actions = {row["id"] for row in catalog["actions"]}
    features = {row["id"] for row in foundation["features"]}
    state_fields = {f"{m['entity']}.{m['state_field']}": mid for mid, m in foundation["machines"].items()}
    builtins = builtin_apis(schema)
    routes = set()
    for aid, api in design["apis"].items():
        signature = api["signature"]
        method, path = signature["method"].upper(), signature["path"]
        import re
        if method not in {"GET","POST","PUT","PATCH","DELETE"} or not re.fullmatch(r'/api(?:/(?:[A-Za-z0-9_-]+|:[A-Za-z][A-Za-z0-9_]*))+', path):
            raise ValueError(f"{aid}: use a concrete /api path with Express colon parameters")
        route = (method, re.sub(r':[A-Za-z][A-Za-z0-9_]*', ':param', path))
        if route in routes:
            raise ValueError(f"{aid}: duplicate canonical HTTP route")
        routes.add(route)
        if method == "GET" and api["write"]:
            raise ValueError(f"{aid}: GET cannot mutate persisted data")
        if aid in builtins:
            if api != builtins[aid]:
                raise ValueError(f"{aid}: compiler-owned identity contract cannot be changed")
            continue
        if api.get("platform_builtin"):
            raise ValueError(f"{aid}: unknown built-in API")
        if "security" not in api or "workflow" not in api or "process_refs" not in api:
            raise ValueError(f"{aid}: supply security and workflow bindings")
        if not set(api["process_refs"]) <= set(evidence["processes"]):
            raise ValueError(f"{aid}: unknown process reference")
        security = api["security"]
        for key in ("mode","permissions","features","resource","action","record_id","operation"):
            if key not in security:
                raise ValueError(f"{aid}: missing security.{key}")
        if security.get("mode") not in {"session", "policy"}:
            raise ValueError(f"{aid}: public/custom authentication is forbidden; use fixed /api/auth endpoints")
        if signature["path"].startswith('/api/auth/') or signature["path"] == "/api/health":
            raise ValueError(f"{aid}: /api/auth is reserved compiler infrastructure")
        perms = security.get("permissions")
        if not isinstance(perms, list) or not set(security.get("features", [])) <= features:
            raise ValueError(f"{aid}: invalid permission/feature bindings")
        for row in perms:
            if row.get("resource") not in resources or row.get("action") not in actions:
                raise ValueError(f"{aid}: unknown resource/action binding")
        business_tables = {s.split('.')[0] for s in api["read"] + api["write"]} & resources
        scoped_reads = {s.split('.')[0] for s in api["read"]} & resources
        missing_scope = scoped_reads - {p["resource"] for p in perms}
        if missing_scope:
            raise ValueError(f"{aid}: business reads require a declared scoped permission for each resource: {sorted(missing_scope)}. Supporting FK lookups also need a source-permitted binding; do not grant new role permissions.")
        if business_tables and (security["mode"] != "policy" or not perms):
            raise ValueError(f"{aid}: business operations require policy authorization")
        if security["mode"] == "policy" and not perms:
            raise ValueError(f"{aid}: policy mode needs a permission")
        if security.get("operation") not in {"read", "create", "update", "delete", "command", "bulk"}:
            raise ValueError(f"{aid}: invalid operation kind")
        resource = security.get("resource")
        if resource is not None and (resource not in resources or resource not in {p['resource'] for p in perms}):
            raise ValueError(f"{aid}: primary resource must have a declared permission")
        primary_action=security.get("action")
        if resource is not None and not any(p["resource"]==resource and p["action"]==primary_action for p in perms):
            raise ValueError(f"{aid}: primary action must have a declared permission")
        if resource is not None and security["operation"] in {"create","update","delete"} and primary_action!=security["operation"]:
            raise ValueError(f"{aid}: mutation operation must bind its actual catalog action")
        written_business={s.split('.')[0] for s in api["write"]}&resources
        if written_business and (security["operation"]=="read" or resource is None):
            raise ValueError(f"{aid}: business writes require a primary mutation permission")
        record_id = security.get("record_id")
        if security.get("record_denial_status",403) not in {403,404} or ("record_denial_status" in security and (resource is None or record_id is None)):
            raise ValueError(f"{aid}: record_denial_status must be 403/404 on a record-scoped API")
        if record_id is not None and (not isinstance(record_id, str) or not __import__('re').fullmatch(r'(params|body|query)\.[A-Za-z][A-Za-z0-9_]*', record_id)):
            raise ValueError(f"{aid}: invalid record selector")
        if security["operation"] in {"update", "delete", "command"} and business_tables and (record_id is None or resource is None):
            raise ValueError(f"{aid}: record mutation requires a trusted record ownership check")
        workflow = api["workflow"]
        if workflow:
            machine = foundation["machines"].get(workflow.get("machine"))
            transition = machine and machine["transitions"].get(workflow.get("transition"))
            if not transition or resource != machine["entity"] or workflow.get("record_id") != record_id or record_id is None:
                raise ValueError(f"{aid}: invalid workflow/record binding")
            if primary_action!=transition["action"]:
                raise ValueError(f"{aid}: workflow must authorize its canonical command action")
            preconditions = {r["id"] for r in api["precondition"]}
            postconditions = {r["id"] for r in api["postcondition"]}
            for group, records, available in (("guard_bindings", transition["guards"], preconditions), ("effect_bindings", transition["effects"], postconditions)):
                bindings = workflow.get(group, {})
                if set(bindings) != {r["id"] for r in records} or not set(bindings.values()) <= available:
                    raise ValueError(f"{aid}: every workflow {group} must bind a canonical P/Q condition")
            effect_fields = domain_effect_fields(transition) | {f"{machine['entity']}.{machine['state_field']}"}
            if not effect_fields <= set(api["write"]):
                raise ValueError(f"{aid}: workflow effects are missing from API write obligations: {sorted(effect_fields-set(api['write']))}")
        bound_machines={workflow["machine"]} if workflow else set()
        for binding in (workflow or {}).get("related_transitions",[]):
            machine=foundation["machines"].get(binding.get("machine"))
            transition=machine and machine["transitions"].get(binding.get("transition"))
            if not transition or not any(p["resource"]==machine["entity"] and p["action"]==transition["action"] for p in perms):
                raise ValueError(f"{aid}: related transition needs canonical permission binding")
            for key,records,conditions in (("guard_bindings",transition["guards"],api["precondition"]),("effect_bindings",transition["effects"],api["postcondition"])):
                bindings=binding.get(key,{})
                if set(bindings)!={r["id"] for r in records} or not set(bindings.values()) <= {r["id"] for r in conditions}:
                    raise ValueError(f"{aid}: related transition needs complete P/Q bindings")
            required={f"{machine['entity']}.{machine['state_field']}"}|domain_effect_fields(transition)
            if not required <= set(api["write"]):raise ValueError(f"{aid}: missing related workflow write effects")
            bound_machines.add(binding["machine"])
        for symbol in set(api["write"]) & set(state_fields):
            if security["operation"] != "create" and state_fields[symbol] not in bound_machines:
                raise ValueError(f"{aid}: state changes require a canonical workflow transition: {symbol}")


def builtin_apis(schema):
    def fields(table):
        return [table+'.'+key for key in schema['entities'][table]['fields']]
    definitions = {}
    for name, method, reads, writes, props in (
        ('login','POST',fields('users')+fields('user_ou_roles')+fields('org_units'),fields('auth_sessions'), {'username':{'type':'string'},'password':{'type':'string'},'unit':{'type':'string'}}),
        ('me','GET',fields('auth_sessions')+fields('users')+fields('user_ou_roles'),[],{}),
        ('logout','POST',fields('auth_sessions'),fields('auth_sessions'),{}),
    ):
        definitions['API-platform-'+name]={'platform_builtin':True,'description':'Compiler-owned account/password '+name,'read':reads,'write':writes,
            'signature':{'name':name,'method':method,'path':'/api/auth/'+name},
            'request':{'params':{'type':'object'},'query':{'type':'object'},'body':{'type':'object','properties':props},'headers':{'type':'object'}},
            'response':{'success':{'status':200,'body':{'type':'object'},'headers':{'type':'object'}},'errors':[{'status':401,'body':{'type':'object'},'headers':{'type':'object'}}]},
            'precondition':[],'postcondition':[], 'security':{'mode':'platform'},'workflow':None}
    user={"type":"object","properties":{"id":{"type":"string"},"username":{"type":"string"},"unitId":{"type":"string"}},"required":["id","username","unitId"]}
    for aid,api in definitions.items():
        api["response"]["success"]["body"] = ({"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"]} if aid.endswith('logout') else {"type":"object","properties":{"user":user,"csrfToken":{"type":"string"}},"required":["user","csrfToken"]})
        if aid.endswith('login'):api["request"]["body"]["required"]=["username","password"]
        if aid.endswith('logout'):api["request"]["headers"]={"type":"object","properties":{"x-csrf-token":{"type":"string"}},"required":["x-csrf-token"]}
    return definitions


def validate_process_coverage(design,foundation,evidence):
    if not foundation.get("enabled"):
        return
    for rid, node in evidence["nodes"].items():
        if node["children"] or rid not in design["requirements"]:
            continue
        covered=set()
        for aid in design["requirements"][rid]:
            api=design["apis"][aid]
            covered.update(api.get("process_refs",[]))
            flow=api.get("workflow")
            if flow:
                covered.update(foundation["machines"][flow["machine"]]["transitions"][flow["transition"]]["process_refs"])
                for binding in flow.get("related_transitions", []):
                    covered.update(foundation["machines"][binding["machine"]]["transitions"][binding["transition"]]["process_refs"])
        missing=set(node["processes"])-covered
        if missing:
            raise ValueError(f"{rid}: APIs omitted cited process behavior: {sorted(missing)}")


def finalize_backend_contracts(design,foundation):
    if not foundation.get("enabled"):
        return design
    for api in design["apis"].values():
        if api.get("platform_builtin"):
            continue
        headers=api["request"].setdefault("headers",{"type":"object"})
        properties=headers.setdefault("properties",{})
        required=headers.setdefault("required",[])
        if api["signature"]["method"].upper() not in {"GET","HEAD","OPTIONS"}:
            properties["x-csrf-token"]={"type":"string"}
            if "x-csrf-token" not in required: required.append("x-csrf-token")
        if api.get("workflow") or api["security"].get("operation")=="bulk":
            properties["idempotency-key"]={"type":"string","minLength":1,"maxLength":128}
            if "idempotency-key" not in required: required.append("idempotency-key")
        errors=api["response"].setdefault("errors",[])
        for status in ({401,403,400,409} if api.get("workflow") or api["security"].get("operation")=="bulk" else {401,403}):
            if not any(row.get("status")==status for row in errors):
                errors.append({"status":status,"body":{"type":"object","properties":{"error":{"type":"string"}},"required":["error"]},"headers":{"type":"object"}})
    return design
