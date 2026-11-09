"""Collect ER, identity, authorization and workflow infrastructure before API design."""

import json
import re

from infrastructure.shared.models.text import TextModel
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.files import read_artifact, save_json
from infrastructure.stages.backend.evidence import compile_evidence, SCOPES

INSTRUCTIONS = '''Compile cross-cutting backend semantics from the original requirement evidence.
Do not implement business code or redesign ER. Only a compiler-generated relationship FK may be made nullable when explicit ordinary-create scenarios contradict mandatory generated-parent cardinality. Record that exceptional adjustment and its source relation/requirements; never change original attributes, keys or types. Return one JSON object:
{
 "default_boundary":"none|unit|unit_tree",
 "schema_adjustments":[{"field":"Table.generated_fk","nullable":true,"requirements":["REQ-ID"],"source_refs":["relation ID"],"reason":"resolve explicit source ER/prose conflict"}],
 "boundary_requirements":["REQ-ID"],
 "additional_permissions":[{"role":"catalog-role","resource":"catalog-resource","action":"catalog-action","scope":"all|own|unit|unit_tree|assigned","effect":"allow|deny","requirements":["REQ-ID"],"reason":"explicit evidence/correction"}],
 "features":[{"id":"stable-feature-id","allowed_roles":["role-id"],"denied_usernames":["explicitly identified account"],"requirements":["REQ-ID"],"reason":"..."}],
 "machines":{"MACHINE-ID":{"entity":"canonical-table","state_field":"existing-field","initial":"source initial state","states":["persisted-state"],"state_actions":{"persisted-state":["catalog-action"]},"requirements":["REQ-ID"],
   "transitions":{"TRANSITION-ID":{"event":"stable-command","action":"catalog-action","roles":["catalog-role"],"assigned_only":false,"from":["persisted-state"],"to":"persisted-state","process_refs":["process-id"],"requirements":["REQ-ID"],
     "guards":[{"id":"G-ID","description":"business precondition"}],"effects":[{"id":"E-ID","description":"observable transactional effect","fields":["Table.field"]}]}}}},
 "process_dispositions":{"process-id":{"mode":"state_machine|operation","machines":["MACHINE-ID"],"requirements":["REQ-ID"],"reason":"how this source process is implemented"}},
 "decisions":[{"requirements":["REQ-ID"],"source_refs":["source path or process/node"],"issue":"source gap/conflict","resolution":"effective behavior and rationale"}]
}
All keys are required. Empty collections are allowed when not supported by evidence.
Normalize tenant/team boundaries from prose/scenarios separately from Casbin scope.
'all' does not remove a source-required tenant boundary.
Administrator cross-unit visibility is already provided by the platform's admin bypass;
it is NOT evidence for granting ordinary members unit_tree access. Use unit for own-team
isolation unless source requirements explicitly grant access to descendant units.
Do not equate every team_member with a demo account. Keep feature entitlements separate from entity resource permissions.
Source CSV remains immutable. additional_permissions are explicit, traceable effective
policy supplements only when prose/scenarios require them. Never narrow administrator
permissions. Missing permission defaults to deny. Do not invent organizational roles.

BPMN is evidence: preserve its source graph, resolve conflicts against business/scenario
requirements and record decisions. Natural-language conditions are not executable code. Bind human command roles from
BPMN lanes and source roles; assigned_only is true only for explicit current-assignee restrictions.
Model source-required commands/states and guards/effects; no mandatory multi-level approval,
assignees or task center unless required. A generic exclusive branch must not suppress two
independent effects both required by source scenarios. Distinguish creating adjustment
records from applying their inventory effects; never double-apply them. State conversions,
all effects and audit are one transaction; retries must not apply effects again. Describe
compensation/reversal using original movements, not merely a status change.
When a source defines missing derived/aggregate data as zero/empty, effects must include
first-use initialization and its primary/association/required fields before applying the
change. Do not turn this valid initial state into an invented rejection or rely on
startup fixtures for every future business key. Include both initialization and update
branches without granting an unrelated user-facing create permission.

Use canonical schema fields exactly. Effects select fields that exist; if a business
concept is absent from ER, record the gap in decisions rather than fabricating columns.
Do not copy screenshot/example values into state definitions, policy or runtime fixtures.
Every decision, machine and supplement must cite existing source requirement IDs.
The compiler separately provides account/password sessions, domain roles, record ownership,
feature checks, command receipts, audit, Casbin and XState. Their private tables are
infrastructure; do not invent business workflows to exercise them.'''


def require_refs(value, nodes):
    refs = value.get("requirements")
    if not isinstance(refs, list) or not refs or not set(refs) <= set(nodes):
        raise ValueError("Backend semantic decisions require existing source requirement IDs")


def validate_foundation(plan, evidence, schema):
    for key in ("schema_adjustments", "default_boundary", "boundary_requirements", "additional_permissions", "features", "machines", "process_dispositions", "decisions"):
        if key not in plan:
            raise ValueError(f"Missing backend foundation property {key}")
    nodes = evidence["nodes"]
    if plan["default_boundary"] not in {"none", "unit", "unit_tree"} or not set(plan["boundary_requirements"]) <= set(nodes):
        raise ValueError("Invalid normalized data boundary")
    if plan["default_boundary"] != "none" and not plan["boundary_requirements"]:
        raise ValueError("A normalized data boundary requires source requirements")
    catalog = evidence["authorization"]["catalog"]
    known = {key: {x["id"] for x in catalog[key]} for key in ("roles", "resources", "actions")}
    for permission in plan["additional_permissions"]:
        require_refs(permission, nodes)
        if permission.get("role") not in known["roles"] or permission.get("resource") not in known["resources"] or permission.get("action") not in known["actions"] or permission.get("scope") not in SCOPES or permission.get("effect") not in {"allow", "deny"} or not permission.get("reason"):
            raise ValueError("Invalid effective permission supplement")
        if permission["role"] == "admin" and permission["effect"] == "deny":
            raise ValueError("Administrator permissions cannot be narrowed")
    features = set()
    for feature in plan["features"]:
        require_refs(feature, nodes)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", feature["id"]) or feature["id"] in features or not set(feature["allowed_roles"]) <= known["roles"]:
            raise ValueError("Invalid feature entitlement")
        if not all(isinstance(name, str) and name for name in feature["denied_usernames"]):
            raise ValueError("Feature denied_usernames must contain explicit account names")
        features.add(feature["id"])
    generated = {item["field"]:item["reason"] for item in schema.get("er_import",{}).get("generated",[]) if item.get("references")}
    for adjustment in plan["schema_adjustments"]:
        require_refs(adjustment,nodes)
        if adjustment.get("field") not in generated or adjustment.get("nullable") is not True or not adjustment.get("reason") or not adjustment.get("source_refs"):
            raise ValueError("Only traceable optionalization of generated relationship FKs is supported")
        if generated[adjustment["field"]] not in adjustment["source_refs"]:
            raise ValueError("Schema adjustment must cite its canonical ER relationship")
    assigned = set()
    for mid, machine in plan["machines"].items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*",mid):
            raise ValueError("Machine IDs must be stable safe identifiers")
        require_refs(machine, nodes)
        entity, state_field = machine["entity"], machine["state_field"]
        if entity not in schema["entities"] or state_field not in schema["entities"][entity]["fields"]:
            raise ValueError(f"Unknown state field in {mid}")
        column = schema["entities"][entity]["fields"][state_field]
        if column["primary_key"] or column["type"] != "string" or entity in assigned:
            raise ValueError(f"State field must have one canonical string-state machine: {mid}")
        assigned.add(entity)
        states = machine["states"]
        if not states or len(set(states)) != len(states) or not all(isinstance(s, str) and s for s in states) or machine["initial"] not in states:
            raise ValueError(f"Invalid machine states: {mid}")
        state_actions = machine.get("state_actions", {})
        if set(state_actions) != set(states) or any(not set(actions) <= known["actions"] for actions in state_actions.values()):
            raise ValueError(f"{mid}: every state needs explicit allowed catalog actions")
        events = set()
        for tid, transition in machine["transitions"].items():
            require_refs(transition, nodes)
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*",tid) or not isinstance(transition.get("event"),str) or not transition["event"]:
                raise ValueError("Invalid canonical transition/event identifier")
            if not transition["from"] or not set(transition["from"]) <= set(states) or transition["to"] not in states:
                raise ValueError(f"Invalid transition states: {mid}/{tid}")
            for state in transition["from"]:
                key = (state, transition["event"])
                if key in events:
                    raise ValueError(f"Ambiguous machine event: {mid}/{key}")
                events.add(key)
            if transition.get("action") not in known["actions"]:
                raise ValueError(f"Invalid workflow action: {mid}/{tid}")
            if not set(transition["roles"]) <= known["roles"] or not isinstance(transition["assigned_only"],bool):
                raise ValueError(f"Invalid workflow actor binding: {mid}/{tid}")
            if any(node["role"] for pid in transition["process_refs"] for node in evidence["processes"].get(pid,{}).get("nodes",{}).values()) and not transition["roles"]:
                raise ValueError(f"{mid}/{tid}: bind human process roles explicitly")
            if not set(transition["process_refs"]) <= set(evidence["processes"]):
                raise ValueError(f"Unknown process reference: {mid}/{tid}")
            for group in ("guards", "effects"):
                records = transition[group]
                if len({r["id"] for r in records}) != len(records):
                    raise ValueError(f"Duplicate {group} IDs: {mid}/{tid}")
                for record in records:
                    if not record.get("description"):
                        raise ValueError(f"Empty {group} description")
                    if group == "effects":
                        for symbol in record["fields"]:
                            table, _, name = symbol.partition(".")
                            if table not in schema["entities"] or name not in schema["entities"][table]["fields"]:
                                raise ValueError(f"Unknown workflow effect field {symbol}")
    dispositions = plan["process_dispositions"]
    if set(dispositions) != set(evidence["processes"]):
        raise ValueError("Every source process needs an explicit implementation disposition")
    for pid, disposition in dispositions.items():
        require_refs(disposition,nodes)
        if disposition.get("mode") not in {"state_machine","operation"} or not disposition.get("reason") or not set(disposition.get("machines",[])) <= set(plan["machines"]):
            raise ValueError(f"Invalid process implementation disposition: {pid}")
        if disposition["mode"] == "state_machine" and not disposition["machines"]:
            raise ValueError(f"{pid}: state-machine disposition needs a machine")
    for decision in plan["decisions"]:
        require_refs(decision, nodes)
        if not decision.get("issue") or not decision.get("resolution") or not decision.get("source_refs"):
            raise ValueError("Source conflicts require traceable explicit resolutions")
    return plan


def add_platform_schema(schema):
    from infrastructure.stages.database.er import field, fingerprint
    def f(kind, description, **options):
        return field(kind, description, nullable=False, **options)
    definitions = {
        "users": {"id": f("uuid", "Identity", primary_key=True), "username": f("string", "Account name", unique=True), "password_hash": f("string", "scrypt credential")},
        "org_units": {"id": f("uuid", "Unit identity", primary_key=True), "code": f("string", "Catalog unit code", unique=True), "name": f("string", "Unit name"), "parent_id": field("uuid", "Parent unit", references="org_units.id")},
        "roles": {"id": f("string", "Catalog role code", primary_key=True), "name": f("string", "Role name")},
        "user_ou_roles": {"id": f("uuid", "Role assignment", primary_key=True), "user_id": f("uuid", "Subject", references="users.id"), "unit_id": f("uuid", "Domain", references="org_units.id"), "role_id": f("string", "Role", references="roles.id")},
        "auth_sessions": {"id": f("string", "SHA256 opaque token", primary_key=True), "user_id": f("uuid", "Subject", references="users.id"), "unit_id": f("uuid", "Active domain", references="org_units.id"), "csrf_token": f("string", "CSRF secret"), "expires_at": f("datetime", "Expiry")},
        "record_access": {"id": f("uuid", "Ownership identity", primary_key=True), "resource": f("string", "Resource code"), "record_id": f("string", "Business record key"), "unit_id": f("uuid", "Record domain", references="org_units.id"), "owner_id": field("uuid", "Owner", references="users.id"), "assignee_id": field("uuid", "Assignee", references="users.id")},
        "command_receipts": {"id": f("string", "Scoped idempotency key", primary_key=True), "request_hash": f("string", "Canonical request hash"), "response": f("json", "Committed response")},
        "workflow_audit": {"id": f("uuid", "Audit identity", primary_key=True), "machine": f("string", "Machine ID"), "record_id": f("string", "Business key"), "event": f("string", "Event"), "from_state": f("string", "Previous state"), "to_state": f("string", "Committed state"), "actor_id": f("uuid", "Trusted subject", references="users.id"), "unit_id": f("uuid", "Trusted domain", references="org_units.id"), "occurred_at": f("datetime", "Timestamp")},
        "platform_meta": {"id": f("string", "Bootstrap marker", primary_key=True), "value": f("string", "Marker value")},
    }
    for name, fields in definitions.items():
        entity = schema["entities"].setdefault(name, {"description": "Compiler-owned backend infrastructure", "origin": "backend_platform", "fields": {}})
        if entity.get("origin") not in {"backend_platform", "reference_target"}:
            raise ValueError(f"Business ER entity {name} collides with reserved backend infrastructure")
        for key, definition in fields.items():
            if key in entity["fields"] and any(entity["fields"][key].get(k) != definition[k] for k in ("type", "primary_key")):
                raise ValueError(f"Incompatible infrastructure field {name}.{key}")
            entity["fields"].setdefault(key, definition)
    schema["entities"]["user_ou_roles"]["unique_constraints"] = [["user_id", "unit_id", "role_id"]]
    schema["entities"]["record_access"]["unique_constraints"] = [["resource", "record_id"]]
    if schema.get("er_import"):
        schema["er_import"]["schema_sha256"] = fingerprint(schema["entities"])
        schema["er_import"]["backend_platform_tables"] = list(definitions)
    return schema


def design_backend_foundation(input_dir, arc_dir, pause=False, max_attempts=10):
    raw = read_artifact(arc_dir, "requirements.json")
    # ER is the database authority. This is deterministic evidence import, not
    # an independent model database-design pass. Metadata supports later checks.
    from infrastructure.stages.database.er import import_er_schema
    imported = import_er_schema(raw, input_dir)
    if imported is None:
        raise ValueError("Database implementation requires published ER evidence; no separate schema inference stage is used")
    save_json(arc_dir / "db_schema.json", imported)
    save_json(arc_dir / "er_import.json", imported["er_import"])
    evidence = compile_evidence(raw, input_dir)
    save_json(arc_dir / "backend_evidence.json", evidence)
    if not evidence["enabled"]:
        from infrastructure.stages.requirements.data import compile_data
        save_json(arc_dir / "data_bindings.json", compile_data(raw, read_artifact(arc_dir, "db_schema.json")))
        save_json(arc_dir / "backend_foundation.json", {"enabled": False})
        return {"status": "GREEN", "enabled": False}
    if not evidence["authorization"]:
        raise ValueError("Process-enabled backend generation requires an explicit authorization catalog/model/policy")
    schema = add_platform_schema(read_artifact(arc_dir, "db_schema.json"))
    save_json(arc_dir / "db_schema.json", schema)
    if schema.get("er_import"):
        save_json(arc_dir / "er_import.json", schema["er_import"])
    payload = {"evidence": evidence, "schema": schema["entities"], "er_mapping": schema.get("er_import",{}),
        "account_names": [r.get("properties", {}).get("username") for r in raw.get("data", []) if r.get("entity") == "test account"]}
    console = DemoConsole(pause)
    plan, _ = propose_json(TextModel(), INSTRUCTIONS, payload,
        lambda value: validate_foundation(value, evidence, schema), console, "Backend shared semantics", max_attempts)
    plan.update(enabled=True, source_hashes=evidence["source_hashes"])
    for adjustment in plan["schema_adjustments"]:
        table,key=adjustment["field"].split('.')
        schema["entities"][table]["fields"][key]["nullable"]=True
    if schema.get("er_import"):
        from infrastructure.stages.database.er import fingerprint
        schema["er_import"]["backend_semantic_adjustments"]=plan["schema_adjustments"]
        schema["er_import"]["schema_sha256"]=fingerprint(schema["entities"])
        save_json(arc_dir / "er_import.json",schema["er_import"])
    # Shared machine effects must be visible before field-obligation inference.
    for machine in plan["machines"].values():
        symbols = {f"{machine['entity']}.{machine['state_field']}"}
        for transition in machine["transitions"].values():
            symbols.update(field for effect in transition["effects"] for field in effect["fields"])
        owners = set(machine["requirements"]) | {rid for t in machine["transitions"].values() for rid in t["requirements"]}
        for rid in owners:
            if schema["requirements"].get(rid):
                schema["requirements"][rid] = sorted(set(schema["requirements"][rid]) | symbols)
    infrastructure_fields = {f"{name}.{key}" for name, entity in schema["entities"].items() if entity.get("origin") in {"backend_platform", "reference_target"} for key in entity["fields"]}
    for rid, fields in schema["requirements"].items():
        if fields:
            schema["requirements"][rid] = sorted(set(fields) | infrastructure_fields)
    save_json(arc_dir / "db_schema.json", schema)
    save_json(arc_dir / "backend_foundation.json", plan)
    from infrastructure.stages.requirements.data import compile_data
    save_json(arc_dir / "data_bindings.json", compile_data(raw, schema))
    from infrastructure.stages.backend.platform_files import publish_platform
    publish_platform(arc_dir.parent, evidence, plan, schema, raw)
    console.show("Backend shared semantics", json.dumps({"boundary": plan["default_boundary"], "machines": list(plan["machines"]), "decisions": plan["decisions"]}, ensure_ascii=False, indent=2))
    return {"status": "GREEN", "enabled": True, "machines": list(plan["machines"])}
