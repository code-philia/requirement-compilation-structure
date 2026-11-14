"""Native ER schema construction and requirement-driven schema/obligation refinement."""

from copy import deepcopy
import json
import re

from infrastructure.shared.agent import BaseAgent, AgentTool, AgentLoopExhausted
from infrastructure.shared.models.streaming import IncompleteModelStreamError


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FIELD = {"type": "object", "properties": {
    "description": {"type": "string"},
    "type": {"type": "string", "enum": ["string", "uuid", "integer", "number", "boolean", "date", "datetime", "json"]},
    "nullable": {"type": "boolean"}, "primary_key": {"type": "boolean"},
    "unique": {"type": "boolean"}, "references": {"anyOf": [
        {"type":"string"},{"type":"null"},
        {"type":"object","properties":{"entity":{"type":"string"},"field":{"type":"string"}},
            "required":["entity"],"additionalProperties":False}],
        "description":"Prefer {entity: targetTable, field: actualKey} or targetTable.actualKey. A bare table is resolved only when it has exactly one PK column; otherwise deferred, never guessed as id."},
    "constraints": {"type": "array", "items": {"type": "string"}},
    "sqlite_type": {"type": "string", "enum": ["TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC"]},
    "source_type": {"type": "string"}},
    "required": ["description", "type", "nullable", "primary_key", "unique", "references", "constraints"],
    "additionalProperties": False}
ENTITY = {"type": "object", "properties": {"description": {"type": "string"},
    "fields": {"type": "object", "additionalProperties": FIELD},
    "unique_constraints": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}},
    "required": ["description", "fields"], "additionalProperties": False}
RECORD = {"type": "object", "properties": {
    key: {"type": "array", "items": {"type": "string"}}
    for key in ("read", "write", "observation_read")},
    "required": ["read", "write"], "additionalProperties": False}

SCHEMA_RULES = """Maintain one logical database schema, NOT SQL or application code.
The COMPLETE original ER Mermaid source is supplied directly in each er_sources entry's content.
Use it as evidence, not an executable contract. No file lookup, path arguments or
paginated reads are needed. Source paths are citation labels only.
Resolve contradictory relationships, duplicate concepts, missing keys, FK collisions,
cardinality and optionality using the evidence; record each nontrivial decision and its
source references. Do not run a deterministic Mermaid-to-schema conversion. Preserve
source business names where coherent, but choose a consistent canonical design when
source conflicts. Record aliases as source_refs in your decisions. Never silently omit
an ER entity/relationship just because it is hard to represent. M:N can use a junction
table; 1:N should normally use one FK, not duplicate representations. Forward references
are allowed across upsert_entity calls. Finish only after all targets and keys resolve.
references accepts {"entity":"target","field":"actual_pk"}, "target.actual_pk", a
bare "target", or null. The host normalizes equivalent forms, defers forward references,
and resolves bare targets ONLY from a known single-column primary key. Never assume id.
Inspect normalized/pending feedback; do not resend already saved fields merely to expand
a resolved FK. At finish, unresolved/ambiguous references are returned together.
Use upsert_entity for one table at a time or many calls together. Updates merge fields
and preserve omitted earlier fields; retrieve unseen definitions before revising them.
Only change existing definitions to repair a concrete evidence-backed defect. Include
all field properties for added fields; supplied properties replace those of existing
fields. Composite keys and entity.unique_constraints are supported. Use nullable=false
for required values/PKs. Exact decimals can use type=string, sqlite_type=TEXT with an
explicit exact-arithmetic constraint; do not invent precision or silently use floats.
Use actual SQLite storage types where helpful. JSON/list checks must be SQLite scalar
checks; cross-row rules belong to application code. Do not store UI-only state.
There are NO preset user, role, organization, session, ownership, audit or platform tables.
Infer whether each responsibility needs persisted data from the ER and current requirement
evidence. user_ref/unit_ref imply a relationship to identify and model, not permission to
inject a fixed platform schema. Create the smallest coherent source-required definitions.
Use the source authorization catalog as evidence for user types, roles and relationships,
not a mandatory table layout. A role is not automatically a separate user table or a public
registration choice. Do not invent administrators, user types, default accounts, sessions,
audit tables or credentials unless required. No fixed table names, account columns, UUID
strategy or tenancy architecture are imposed. Preserve source terminology and record any
necessary canonical-name bindings in source_refs. Write a specific description per entity.
Gather enough evidence then publish definitions promptly. Batch independent reads and
updates; do not repeatedly retrieve already supplied definitions. Native tools only.
Explicit source_data/SEED accounts and startup facts are modeling evidence alongside ER.
Even if ER omits credentials, model a secure persisted credential representation and
ALL source role/unit bindings. Never narrow roles to unrelated business labels or omit
an administrator declared by source data/catalog. Do not put plaintext passwords into
schema defaults. Later seed implementation must be able to preserve all supplied facts.
"""

OBLIGATION_RULES = """For requirement r, O(r)=(R(r),W(r)):
R contains existing persistent values required by specified behavior, including displayed
values, lookup/filter/join keys, existence checks, authentication and authorization data.
W contains fields whose persisted values or record existence are created, changed or
removed, including generated keys. Both sets cover possible specified branches, not
mandatory SQL accesses on every invocation or an exhaustive access whitelist.
Infer each step from its current When and Then. Given is pre-existing context, NOT writes
performed by the current behavior. A returned newly generated ID is a write, not a read
of a pre-existing value. Rejection/cancel/unchanged state has no writes unless specified.
Hard deletion writes all removed fields including PK; soft deletion writes changed flags.
Reload/opening reads persisted values even after an earlier create returned them.
Local-only UI behavior can have empty sets. Do not inherit another requirement's effects
merely through parent context, dependencies or reference links. For a parent requirement,
analyze its own explicit behavior; child summaries do not require copying all child effects.
Requirement sets cover all its own step sets and additional behavior in its description.
For a materialized aggregate initially absent, creation keys/required fields are possible
writes; do not assume scenario fixtures or future data are system startup seeds.
Acceptance-only DB inspections can go into observation_read, not business read.
Do not assume an external platform supplies identity, audit, idempotency or ownership.
Include their persistent reads/writes when the current source behavior requires them;
source-required assignee/state/ledger changes are genuine effects.
Use exact canonical Entity.field symbols. Candidate retrieval is a hint, not a whitelist.
If the schema cannot express the behavior, REPAIR it with upsert_entity before submission.
Preserve earlier obligations and unrelated definitions. Do not fake empty obligations
to bypass missing fields. Finish with submit_obligations for this requirement and EVERY
supplied step (steps={} when none), all together. No separate schema-design pass per node.
"""


def reference_value(value):
    """Canonical syntax, without choosing an ambiguous target key."""
    if value is None:
        return None
    if isinstance(value,dict):
        if set(value)-{'entity','field'} or not isinstance(value.get('entity'),str):
            raise ValueError('references object needs entity and optional field only')
        target, field = value['entity'], value.get('field')
        if not IDENTIFIER.fullmatch(target) or (field is not None and (not isinstance(field,str) or not IDENTIFIER.fullmatch(field))):
            raise ValueError('Use SQL-safe entity/field identifiers for references')
        return target+'.'+field if field is not None else target
    if isinstance(value,str):
        value = value.strip()
        if len(value.split('.')) in {1,2} and all(IDENTIFIER.fullmatch(part) for part in value.split('.')):
            return value
    raise ValueError('references must be null, Entity.field, a table name, or {entity, field}')


def normalize_references(schema):
    """Resolve all newly available forward references; preserve uncertain targets."""
    normalized, pending = [], []
    entities = schema['entities']
    for name,entity in entities.items():
        for key,field in entity['fields'].items():
            original = field.get('references')
            if original is None:
                continue
            try:
                ref = reference_value(original)
            except ValueError as error:
                pending.append({'field':name+'.'+key,'reason':str(error)})
                continue
            target, separator, column = ref.partition('.')
            target_fields = entities.get(target,{}).get('fields',{})
            if not separator:
                primary = [column for column,definition in target_fields.items() if definition.get('primary_key')]
                if len(primary)==1:
                    ref = target+'.'+primary[0]
                else:
                    pending.append({'field':name+'.'+key,'target':target,'primary_key_candidates':primary,
                        'reason':'Target is not defined yet' if target not in entities else 'Choose an explicit unique target column; target has no single-column PK'})
            elif column not in target_fields:
                pending.append({'field':name+'.'+key,'target':ref,'reason':'Target field is not defined yet'})
            if original != ref:
                field['references'] = ref
                change = {'field':name+'.'+key,'from':deepcopy(original),'to':ref}
                normalized.append(change)
                history = schema.setdefault('reference_normalizations',[])
                if change not in history:
                    history.append(change)
    return {'normalized':normalized,'pending':pending}


def schema_issues(schema):
    """Executable representation checks, not ER semantic equivalence validation."""
    issues = []
    entities = schema["entities"]
    for name, entity in entities.items():
        fields = entity["fields"]
        if not fields or not any(f["primary_key"] for f in fields.values()):
            issues.append(f"{name}: define fields and a primary key")
        for group in entity.get("unique_constraints", []):
            if not group or any(key not in fields for key in group):
                issues.append(f"{name}: invalid composite UNIQUE {group}")
        for key, field in fields.items():
            ref = field.get("references")
            if not ref:
                continue
            try:
                ref = reference_value(ref)
            except ValueError as error:
                issues.append(f'{name}.{key}: {error}')
                continue
            target, sep, column = ref.partition(".")
            target_fields = entities.get(target, {}).get("fields", {})
            if not sep or column not in target_fields:
                issues.append(f"{name}.{key}: unresolved FK {ref}")
            elif not target_fields[column]["unique"] and not (
                    target_fields[column]["primary_key"] and
                    sum(f["primary_key"] for f in target_fields.values()) == 1) and [column] not in entities[target].get("unique_constraints", []):
                issues.append(f"{name}.{key}: FK target {ref} must have a single-column PK/UNIQUE")
    return issues


class DatabaseDesignAgent(BaseAgent):
    def __init__(self, schema, sources, *, mode="er", persist=None, **options):
        super().__init__(**options)
        self.schema, self.sources, self.mode = schema, sources, mode
        self.persist = persist or (lambda: None)
        self.completed = None
        self.input = {}

    def build_system_prompt(self):
        if self.mode == "er":
            return SCHEMA_RULES + ('\nRead ER and ALL supplied requirements/source_data/evidence together. Build the COMPLETE schema before SQL. '
                'Review cross-cutting persistence and source SEED representability now; no later per-node SQL corrections or obligatory fixed infrastructure. '
                'In finish_schema provide requirement_support for every supplied requirement ID: entities plus a short reason. '
                'UI-only behavior may use entities=[] with an explanation. This is a coverage inventory, not read/write obligations.')
        return SCHEMA_RULES + "\n" + OBLIGATION_RULES

    def build_user_prompt(self, input):
        return {**input, "er_sources": {path: {"content": text}
                for path, text in self.sources.items()},
            "entity_inventory": {name: {"description": entity["description"],
                "fields": list(entity["fields"]), "origin": entity.get("origin", "agent"),
                "source_refs": entity.get("source_refs", [])}
                for name, entity in self.schema["entities"].items()}}

    def build_tools(self):
        tools = [AgentTool("retrieve_entity", "Read complete canonical definitions for several named entities together.",
                {"type": "object", "properties": {"names": {"type": "array", "items": {"type": "string"}}},
                 "required": ["names"], "additionalProperties": False}, self.retrieve_entity),
            AgentTool("upsert_entity", "Create one logical table or merge an evidence-backed repair; never generate code here.",
                {"type": "object", "properties": {"name": {"type": "string"}, "entity": ENTITY,
                    "reason": {"type": "string"}, "source_refs": {"type": "array", "items": {"type": "string"}}},
                 "required": ["name", "entity", "reason", "source_refs"], "additionalProperties": False}, self.upsert_entity)]
        if self.mode == "er":
            tools.append(AgentTool("finish_schema", "Finish the complete ER-based logical schema; unresolved FK/key issues are repair feedback.",
                {"type": "object", "properties": {"summary": {"type": "string"},
                    "requirement_support":{"type":"object","additionalProperties":{"type":"object","properties":{
                        "entities":{"type":"array","items":{"type":"string"}},"reason":{"type":"string"}},
                        "required":["entities","reason"],"additionalProperties":False}}},
                    "required": ["summary"], "additionalProperties": False}, self.finish_schema))
        else:
            tools.append(AgentTool("submit_obligations", "Submit complete current requirement and scenario-step effects after schema repairs.",
                {"type": "object", "properties": {"requirement": RECORD,
                    "steps": {"type": "object", "additionalProperties": RECORD}},
                 "required": ["requirement", "steps"], "additionalProperties": False}, self.submit_obligations))
        return tools

    def retrieve_entity(self, names):
        return {"entities": {name: self.schema["entities"][name] for name in names if name in self.schema["entities"]},
            "missing": [name for name in names if name not in self.schema["entities"]]}

    def upsert_entity(self, name, entity, reason, source_refs):
        if self.completed is not None:
            raise ValueError("Completion must be the last call in the batch")
        if not IDENTIFIER.fullmatch(name) or not reason or not source_refs:
            raise ValueError("Use an SQL-safe canonical name and cite evidence/reason")
        current = self.schema["entities"].get(name, {})
        updated = deepcopy(current or {"origin": "agent_er" if self.mode == "er" else "agent_requirement", "fields": {}})
        syntax_changes = []
        updated["description"] = entity.get("description", updated.get("description", name))
        for key, definition in entity.get("fields", {}).items():
            if not IDENTIFIER.fullmatch(key):
                raise ValueError(f"Invalid field name {key}")
            field = {**updated["fields"].get(key, {}), **definition}
            missing = set(FIELD["required"]) - field.keys()
            if missing or field.get("type") not in FIELD["properties"]["type"]["enum"]:
                raise ValueError(f"{name}.{key}: invalid type or missing field properties {sorted(missing)}")
            for flag in ("nullable", "primary_key", "unique"):
                if not isinstance(field[flag], bool):
                    raise ValueError(f"{name}.{key}.{flag} must be boolean")
            if not isinstance(field["constraints"], list) or any(not isinstance(v, str) for v in field["constraints"]):
                raise ValueError(f"{name}.{key}.constraints must be strings")
            original_reference = deepcopy(field['references'])
            field['references'] = reference_value(original_reference)
            if original_reference != field['references']:
                syntax_changes.append({'field':name+'.'+key,'from':original_reference,'to':field['references']})
            if field["primary_key"]:
                field["nullable"] = False
            updated["fields"][key] = field
        if "unique_constraints" in entity:
            groups = entity["unique_constraints"]
            updated["unique_constraints"] = list({tuple(group): group for group in groups}.values())
        updated["source_refs"] = sorted(set(updated.get("source_refs", [])) | set(source_refs))
        if updated==current:
            references = normalize_references(self.schema)
            if references['normalized']:
                self.persist()
            references['normalized'] = syntax_changes+references['normalized']
            return {'unchanged':name,'fields':list(updated['fields']),
                'references':references,
                'next_action':'Definition is retained. Advance to the next needed table or completion rather than repeating it.'}
        self.schema["entities"][name] = updated
        references = normalize_references(self.schema)
        references['normalized'] = syntax_changes+references['normalized']
        for change in syntax_changes:
            history = self.schema.setdefault('reference_normalizations',[])
            if change not in history:
                history.append(change)
        self.schema.setdefault("decisions", []).append({"entity": name, "reason": reason,
            "source_refs": source_refs, "requirement": self.input.get("requirement", {}).get("id")})
        self.persist()
        return {"saved": name, "fields": list(updated["fields"]), 'references':references,
            'next_action':'Keep saved definitions. Continue with other tables; normalized references need no resubmission. Resolve pending choices before finish_schema.'}

    def ensure_complete(self):
        references = normalize_references(self.schema)
        if references['normalized']:
            self.persist()
        issues = schema_issues(self.schema)
        if not self.schema["entities"] or issues:
            raise ValueError("Repair schema before completing: " + "; ".join(issues or ["no entities"]))

    def finish_schema(self, summary, requirement_support=None):
        expected = {node['id'] for node in self.input.get('requirements',[])}
        if expected:
            support = requirement_support if requirement_support is not None else self.schema.get('requirement_support',{})
            missing = sorted(expected-support.keys())
            invalid = [rid for rid in expected & support.keys() if not isinstance(support[rid],dict)
                or not isinstance(support[rid].get('entities'),list)
                or not isinstance(support[rid].get('reason'),str) or not support[rid]['reason'].strip()]
            unknown = {rid:sorted(set(item['entities'])-self.schema['entities'].keys()) for rid,item in support.items()
                if rid in expected and rid not in invalid and set(item['entities'])-self.schema['entities'].keys()}
            if missing or invalid or unknown:
                return {'status':'COVERAGE_PENDING','missing_requirement_ids':missing,'invalid_entries':invalid,
                    'unknown_entities':unknown,'next_action':'Complete the short requirement_support inventory in finish_schema; keep existing entity definitions. No per-node redesign is needed.'}
            self.schema['requirement_support'] = {rid:deepcopy(support[rid]) for rid in sorted(expected)}
            self.persist()
        references = normalize_references(self.schema)
        if references['normalized']:
            self.persist()
        issues = schema_issues(self.schema)
        if not self.schema['entities'] or issues:
            return {'status':'NEEDS_DECISION','issues':issues or ['No entities defined'],**references,
                'next_action':'Resolve all listed FK/key ambiguities in one batch, then finish_schema. Valid definitions and requirement_support are retained; no need to resend them.',
                'reference_example':{'entity':'actual_target_table','field':'actual_unique_key'}}
        self.completed = {"summary": summary}
        return {"status": "COMPLETE", "entities": len(self.schema["entities"])}

    def submit_obligations(self, requirement, steps):
        from infrastructure.stages.database.obligations.records import check_symbols, normalize_record
        expected = {step["id"] for step in self.input["steps"]}
        if set(steps) != expected:
            raise ValueError(f"Include exactly these step IDs: {sorted(expected)}")
        self.ensure_complete()
        inferred = {"requirement": normalize_record(requirement),
            "steps": {sid: normalize_record(record) for sid, record in steps.items()}}
        # Requirement effects are the union of its own explicitly supplied effects
        # and step effects; set aggregation need not consume a model repair round.
        for mode in ("read", "write", "observation_read"):
            inferred["requirement"][mode] = sorted(set(inferred["requirement"].get(mode, [])) |
                {field for record in inferred["steps"].values() for field in record.get(mode, [])})
        check_symbols([inferred["requirement"], *inferred["steps"].values()], self.schema)
        self.completed = inferred
        return {"status": "COMPLETE"}

    def run(self, input, max_turns=20):
        self.input, self.completed = input, None
        self.start(input)
        for _ in range(max_turns):
            try:
                # Thinking mode supports native tools with auto selection, but
                # rejects forced tool_choice=required. Completion remains explicit.
                message = self.step(tool_choice="auto")
            except (ValueError, IncompleteModelStreamError) as error:
                self.messages.append({"role": "user", "content": str(error) + " Return a smaller complete native tool batch."})
                continue
            if not message.tool_calls:
                completion_tool = getattr(self,'completion_tool_name',"finish_schema" if self.mode == "er" else "submit_obligations")
                self.messages.append({"role": "user", "content":
                    f"The task is not complete. Use the native tools to perform the work, "
                    f"then call {completion_tool}. A text-only answer does not submit a result."})
                continue
            results = self.execute_tools(message)
            if self.completed is not None and all(json.loads(item["content"])["ok"] for item in results):
                return self.completed
            self.completed = None
        raise AgentLoopExhausted(f"Database {self.mode} task exhausted {max_turns} turns; partial schema saved")
