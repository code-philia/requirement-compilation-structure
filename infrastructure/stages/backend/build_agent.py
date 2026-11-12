"""One native agent per leaf: design, generate tests, then TDD in one history."""

from copy import deepcopy
import hashlib
import json
import re

from infrastructure.shared.agent import AgentTool, BaseAgent, AgentLoopExhausted
from infrastructure.shared.agent.feedback import compact_feedback, failure_signature
from infrastructure.shared.agent.native_files import native_file_definition, execute_native_file
from infrastructure.shared.models.streaming import IncompleteModelStreamError
from infrastructure.shared.rag.backend import BackendRetriever
from infrastructure.stages.backend.graph import refresh_graph, coverage, roots, closure
from infrastructure.stages.backend.budget import BackendBudget, READ_TOOLS

STRINGS = {'type': 'array', 'items': {'type': 'string'}}
SHAPE = {'type': 'object', 'additionalProperties': True}
COMMON = {'description': {'type': 'string'}, 'name': {'type': 'string'},
    'input': SHAPE, 'output': SHAPE,
    'direct_read': {**STRINGS, 'description': 'Actual persistent fields read by this operation itself, excluding callees'},
    'direct_write': {**STRINGS, 'description': 'Actual persistent fields changed by this operation itself, excluding callees'},
    'callees': {**STRINGS, 'description': 'Directly called internal module IDs; total read/write and callers are derived'},
    'implementation': {'type': 'string', 'description': 'Concrete backend/src/*.ts implementation file'},
    'precondition': STRINGS, 'postcondition': STRINGS, 'errors': STRINGS,
    'source_refs': STRINGS}
REQUIRED = ['description','name','input','output','direct_read','direct_write','callees','implementation']

RULES = '''Complete ONE leaf requirement in this SAME conversation, in this order:
1. DESIGN: retrieve/reuse APIs and modules, define I/O, effects, callees and actual files,
   associate the requirement and resolve reported effect gaps using real direct effects
   or actual callee links, then call begin_tests. Batch independent design calls;
   association and begin_tests may follow in that same ordered tool batch.
2. GENERATE TESTS: use write_test to implement source-based node:test acceptance BEFORE
   production code. Normally call begin_tdd immediately after write_test: it observes
   initial RED automatically. Use standalone run_tests only for an intermediate diagnosis.
   Missing implementation imports/routes are actionable initial feedback, not a
   reason to invent fixtures or weaken tests. A genuinely reused capability may already
   be GREEN: never manufacture a failing test just to force RED.
3. TDD IMPLEMENTATION: implement real sources with edit_file, then finish_requirement
   to verify and publish in one call. Use run_tests for intermediate diagnosis as needed.
   Batch independent writes and put verification last. Keep the same context.

Each phase has its main tools. Read/search stay available for concrete missing facts.
There are NO separate discovery or model-call budgets. Normally inspect enough evidence
in one or two focused batches, then advance. Repeated reads/searches cause soft progress
reminders; reuse retained results instead of browsing the whole application. Do not
implement siblings. ancestor_rules constrain the current leaf and do not expand scope.
The only budget is up to 10 implementation test/fix iterations (configurable).
Initial test-generation RED and publishing cached GREEN do not consume it. Repeated
unchanged failures reuse diagnostics but still count as retries. Source
compilation failures during implementation do count. Repeated failures require a new
concrete diagnosis/repair strategy or an evidenced blocker, not another identical check.

API and module DESIGN
APIs expose HTTP data/actions; reusable modules implement services, repositories,
calculations, validation, permissions, workflows and integrations. Define real function
names, input/output JSON Schemas, direct_read/direct_write, module callees, and concrete
backend/src/*.ts locations. The host derives inclusive effects, callers and requirement
associations. API input describes HTTP params/query/body/headers, output status/body and
errors. Database handles and trusted identity are internal dependencies, never client
claims. Modules may have no API. Do not invent an endpoint just to test internal code.

RAG combines BM25 with SAME-MODE read/write coverage. Inspect input/output, source meaning,
guards and extra_write before reuse; overlap is not semantic equivalence or permission
to mutate unrelated data. Initial retrieval supplies candidate summaries, not full I/O.
Batch selected IDs in get_capabilities for exact contracts and their callee closure before
reuse. Do not fetch every candidate. Full definitions are returned once per changed record.
A retrieval miss does not prove absence. Use a targeted query for a concrete missing
shared owner, not broad repeated discovery. Unchanged reuse only needs association and
real verification. During implementation keep definitions aligned with actual code;
source-backed interface corrections do not require restarting the agent.
For small corrections use patch_capabilities with only changed fields, not complete API
definitions. Keep each native call small and valid JSON; successful batch calls persist
even if another call fails. Do not resend successful registrations.

SOURCE AUTHORITY
The DB schema, DDL and explicit startup data are already implemented. Do not change them
or invent preset identity/role/organization/session tables, accounts or auth routes.
Implement source-required identity, user types, permissions, features, workflows and
transactions from actual evidence and schema. Empty policy/config lists never waive
source behavior. Capture actual persisted IDs rather than treating catalog codes as IDs.
Use source codes/decimal storage exactly. Materialize initially absent aggregates when
source defines absence as zero/empty; never rely on fixtures to create operation results.

TESTS
Use node:test/node:assert and task.test_path. Name each source scenario ID in executed
test titles. Public behavior uses real HTTP (fetch), never imported handlers/mocks.
Internal-only behavior can test actual module exports. createApiTest(t) from
 task.support_module provides {database,baseURL}; use the database only for isolated
Given and observations. fixturePasswordHash matches the seed scrypt format. Use source
credentials and ACTUAL transport; fixed loginSession/ownGiven/sessionIdentity helpers
apply only if their contract matches the implemented source system. Do not assume a
fixed login URL. Never seed When/Then results, launch a separate server or fake responses.
Freeze the generated suite when entering TDD. For a real current-suite mechanics defect,
repair_test_mechanics with source evidence permits a targeted correction via write_test;
preserve all original expectations. Previously accepted tests are always readonly.
The test_mechanics_reference supplied at startup describes the fixed runner. Reuse it;
read helper implementations only for an exact missing fact. Cast SQL query .get()/.all()
results to the actual row type before accessing properties (strict TypeScript).

IMPLEMENTATION
Register APIs in task.registry via registerModuleApis(app,connection), already connected
by the host. Preserve earlier registrations/callers; don't rewrite host aggregators or
create duplicate APIs. Use parameterized SQL, exact decimal arithmetic where required,
trusted authorization and atomic rejection/rollback. require_dependency declares a
necessary library; host manages installation/scripts. No production fixture shortcuts,
WHEN pre-execution, mocks, test-sensitive code, or schema/seed changes.
edit_file requires path, operation, new_content. create only for exists=false; for existing
files use replace with unique exact old_content, or append/prepend. Compiler registrars
already exist. No new_path/rename or tool/arguments/changes wrappers. Batch independent
writes together. write_test targets the current suite automatically and needs no path.

finish_requirement publishes only actual accepted capabilities. Reuse saved context and
failure evidence. If no backend behavior exists and effects are empty, skip_backend with
source reasoning; empty DB effects alone do not make a pure server calculation UI-only.
Report a specific blocker with evidence when progress is genuinely impossible.
'''


class BackendBuildAgent(BaseAgent):
    def __init__(self, graph, schema, rid, files, gate, *, persist=None,
            acceptance_fingerprint=None, test_gate=None, **options):
        super().__init__(**options)
        self.graph, self.schema, self.rid, self.files, self.gate = deepcopy(graph), schema, rid, files, gate
        self.accepted_graph = deepcopy(graph)
        self.logger.name = type(self).__name__ + ':' + rid
        self.persist = persist or (lambda graph: None)
        self.phase = 'design'
        self.completed = None
        self.associated = False
        self.tests_frozen = False
        self.test_repairs = 0
        self.retriever = BackendRetriever()
        self.retrieval_cache = {}
        self.capability_observations = {}
        self.revision = 0
        self.initial_ids = set(graph['apis']) | set(graph['modules'])
        self.require_build = False
        self.changed_capabilities = set()
        self.pending_dependencies = False
        self.last_feedback = None
        self.budget = BackendBudget.from_environment()
        self.acceptance_fingerprint = acceptance_fingerprint
        self.test_gate = test_gate
        self.acceptance_attempted = False
        self.last_check_state = None
        self.last_failure_signature = None
        self.same_failures = 0
        self.failure_counts = {}
        self.strategies = set()
        self.blocker = None
        self.read_streak = 0
        self.read_observations = set()
        self.code_revision = 0
        self.allow_test_repair = False
        self.baseline_state = None
        self.baseline_result = None
        self.test_ok = False
        self.last_test_result = None
        self.stop_reason = None
        self.no_progress_rounds = 0

    def build_system_prompt(self):
        return RULES

    def build_user_prompt(self, input):
        return {**input, 'agent_budget':self.budget.state()}

    def tool_error_feedback(self, call, error):
        result = super().tool_error_feedback(call,error)
        if call.function.name in {'write_test','edit_file','repair_test_mechanics'}:
            result['next_action'] = ('For a current-suite correction call repair_test_mechanics with source evidence, '
                'then write_test for all necessary local edits before verification. Production edits use edit_file. '
                'Previous suites remain readonly.')
        return result

    def build_tools(self):
        tools = []
        # Design metadata remains editable during TDD when evidence reveals a real
        # interface correction. Code-writing tools are specific to the phase.
        for kind in ('api','module'):
            fields, required = deepcopy(COMMON), list(REQUIRED)
            if kind == 'api':
                fields.update(method={'type':'string'},path={'type':'string'})
                required += ['method','path']
            def bind_kind(selected):
                return lambda id, definition: self.upsert(selected,id,definition)
            tools.append(AgentTool('upsert_'+kind,'Define/update real I/O, direct effects, callees and implementation owner; preserve accepted callers.',
                {'type':'object','properties':{'id':{'type':'string'},'definition':{'type':'object',
                    'properties':fields,'required':required,'additionalProperties':False}},
                 'required':['id','definition'],'additionalProperties':False},bind_kind(kind)))
        tools += [AgentTool('associate_requirement','Associate this leaf with API entry IDs and internal module roots.',
                {'type':'object','properties':{'api_ids':STRINGS,'module_ids':STRINGS},'required':['api_ids','module_ids'],'additionalProperties':False},self.associate),
            AgentTool('patch_capabilities','Correct existing designs using only changed fields, e.g. direct_read or callees; no source edit or test rerun needed for metadata alone.',
                {'type':'object','properties':{'patches':{'type':'array','items':{'type':'object','properties':{
                    'id':{'type':'string'},'changes':{'type':'object','properties':{**COMMON,'method':{'type':'string'},'path':{'type':'string'}},
                        'additionalProperties':False}},'required':['id','changes'],'additionalProperties':False}}},
                    'required':['patches'],'additionalProperties':False},self.patch_capabilities),
            AgentTool('get_capabilities','Batch selected IDs to read exact contracts and callee closure before reuse; unchanged definitions return retained-context references.',
                {'type':'object','properties':{'ids':STRINGS},'required':['ids'],'additionalProperties':False},self.get_capabilities),
            AgentTool('retrieve_schema','Read named canonical tables; already supplied tables return retained-context references.',
                {'type':'object','properties':{'names':STRINGS},'required':['names'],'additionalProperties':False},self.retrieve_schema),
            AgentTool('discard_draft','Remove only unaccepted draft capability IDs, preserving all accepted owners.',
                {'type':'object','properties':{'ids':STRINGS},'required':['ids'],'additionalProperties':False},self.discard_draft),
            AgentTool('change_repair_strategy','Record a new evidence-based diagnosis and concrete different actions after repeated failure.',
                {'type':'object','properties':{'diagnosis':{'type':'string'},'evidence':STRINGS,'actions':STRINGS},'required':['diagnosis','evidence','actions'],'additionalProperties':False},self.change_repair_strategy),
            AgentTool('report_blocker','Report a specific evidenced blocker, ending only this leaf attempt.',
                {'type':'object','properties':{'reason':{'type':'string'},'evidence':STRINGS},'required':['reason','evidence'],'additionalProperties':False},self.report_blocker)]
        if self.accepted_graph['apis'] or self.accepted_graph['modules']:
            tools.append(AgentTool('search_capabilities','Hybrid search of accepted APIs/modules for a named missing reuse candidate.',
                {'type':'object','properties':{'query':{'type':'string'}},'required':['query'],'additionalProperties':False},self.search_capabilities))
        for schema in self.files.schemas():
            name = schema['tool']
            if name not in {'read_file','list_files','search_files','edit_file','bash'}:
                continue
            if name == 'edit_file' and self.phase != 'implementation':
                continue
            description, parameters = native_file_definition(schema)
            def bind_file(selected):
                def invoke(**arguments):
                    if selected == 'edit_file':
                        if self.phase != 'implementation':
                            raise ValueError('Generate tests and call begin_tdd before production edits')
                        if arguments.get('path') == self.task['test_path']:
                            raise ValueError('Use write_test for the current suite; accepted tests remain readonly')
                    self.completed = None
                    result = execute_native_file(self.files,selected,arguments)
                    if selected == 'edit_file' and any(c['before'] != c['after'] for c in self.files.last_changes):
                        self.code_revision += 1
                    return result
                return invoke
            tools.append(AgentTool(name,description,parameters,bind_file(name)))
        if self.phase == 'design':
            tools += [AgentTool('begin_tests','Complete current design/association and move to writing source-based tests in this same history.',
                {'type':'object','properties':{},'additionalProperties':False},self.begin_tests),
                AgentTool('skip_backend','Explain an exclusively frontend/container requirement with empty backend effects.',
                {'type':'object','properties':{'reason':{'type':'string'}},'required':['reason'],'additionalProperties':False},self.skip_backend)]
        else:
            edit = next(s for s in self.files.schemas() if s['tool']=='edit_file')
            _, parameters = native_file_definition(edit)
            parameters['properties'].pop('path',None)
            parameters['required'] = [k for k in parameters['required'] if k != 'path']
            if self.phase == 'tests' or not self.require_build:
                tools.append(AgentTool('write_test','Write only task.test_path. Required operation/new_content; replace also needs exact old_content. No path/new_path. During TDD first obtain repair_test_mechanics permission; multiple local corrections remain allowed until verification. Preserve source assertions.',parameters,self.write_test))
            tools.append(AgentTool('run_tests','Optional intermediate diagnosis. begin_tdd observes initial RED; finish_requirement runs final current/cumulative acceptance. Unchanged observations are reused.',
                {'type':'object','properties':{},'additionalProperties':False},self.run_tests))
            tools.append(AgentTool('require_dependency','Declare a needed npm library; host installs before real verification.',
                {'type':'object','properties':{'name':{'type':'string'},'version':{'type':'string'},'reason':{'type':'string'}},'required':['name','version','reason'],'additionalProperties':False},self.require_dependency))
            if self.phase == 'tests':
                tools.append(AgentTool('begin_tdd','Retain generated tests, observe initial RED if needed, then enable production implementation.',
                    {'type':'object','properties':{},'additionalProperties':False},self.begin_tdd))
            else:
                tools.append(AgentTool('finish_requirement','Publish the completed graph only after real acceptance; reuses unchanged passing tests.',
                    {'type':'object','properties':{},'additionalProperties':False},self.finish))
                if not self.require_build:
                    tools.append(AgentTool('repair_test_mechanics','Permit a source-evidenced correction of CURRENT test mechanics only; never weaken original behavior or prior suites.',
                        {'type':'object','properties':{'reason':{'type':'string'},'source_refs':STRINGS},'required':['reason','source_refs'],'additionalProperties':False},self.repair_test_mechanics))
        return tools

    def upsert(self, kind, id, definition):
        other, section = ('modules','apis') if kind == 'api' else ('apis','modules')
        if id in self.graph[other]:
            raise ValueError('ID already belongs to ' + other)
        if not isinstance(id,str) or not id.strip():
            raise ValueError('Use a nonempty stable capability ID')
        if any(key not in definition for key in REQUIRED):
            raise ValueError('Supply description, name, input/output, direct effects, callees and implementation')
        for key in ('input','output'):
            if not isinstance(definition[key],dict):
                raise ValueError(key + ' must be an inline JSON Schema object')
        for key in ('direct_read','direct_write','callees'):
            if not isinstance(definition[key],list) or any(not isinstance(v,str) for v in definition[key]):
                raise ValueError(key + ' must be an array of strings')
        record = deepcopy(definition)
        record['kind'] = kind
        if kind == 'api':
            record['signature'] = {'name':record['name'],'method':record.pop('method'),'path':record.pop('path')}
        previous = {key:value for key,value in self.graph[section].get(id,{}).items()
            if key not in {'read','write','callers'}}
        if previous == record:
            return {'unchanged':id,'next_action':'Definition is already retained; advance to tests or real implementation instead of resubmitting it.'}
        self.graph[section][id] = record
        self.changed_capabilities.add(id)
        self.completed = None
        self.revision += 1
        self.persist(self.graph)
        return {'saved':id, 'note':'Forward module references may be defined before begin_tests/finish_requirement'}

    def associate(self, api_ids, module_ids):
        api_ids, module_ids = list(dict.fromkeys(api_ids)), list(dict.fromkeys(module_ids))
        if (self.graph['requirements'].get(self.rid) != api_ids
                or self.graph['requirement_modules'].get(self.rid) != module_ids):
            self.revision += 1
        self.graph['requirements'][self.rid] = api_ids
        self.graph['requirement_modules'][self.rid] = module_ids
        self.associated = True
        self.completed = None
        self.persist(self.graph)
        result = {'associated':self.rid}
        # Forward declarations are allowed; coverage feedback must not reject them.
        try:
            refresh_graph(self.graph,self.schema)
            result['design_feedback'] = self.design_feedback()
        except ValueError as error:
            result['design_note'] = str(error)
        return result

    def patch_capabilities(self, patches):
        saved = []
        for patch in patches:
            identity, changes = patch['id'], patch['changes']
            kind = 'api' if identity in self.graph['apis'] else 'module'
            section = 'apis' if kind == 'api' else 'modules'
            if identity not in self.graph[section]:
                raise ValueError('Unknown capability: '+identity+'; earlier successful patches remain saved')
            allowed = set(COMMON) | ({'method','path'} if kind == 'api' else set())
            if not isinstance(changes,dict) or set(changes)-allowed:
                raise ValueError('Patch only declared design fields for '+identity)
            record = self.graph[section][identity]
            definition = {key:deepcopy(value) for key,value in record.items() if key in COMMON}
            if kind == 'api':
                definition.update(method=record['signature']['method'],path=record['signature']['path'])
            definition.update(changes)
            self.upsert(kind,identity,definition)
            saved.append(identity)
        refresh_graph(self.graph,self.schema)
        self.persist(self.graph)
        return {'saved':saved,'design_feedback':self.design_feedback(),
            'next_action':'Metadata is updated. Reuse unchanged passing verification; only edit source if actual behavior needs repair.'}

    def design_feedback(self):
        gaps = coverage(self.graph,self.rid,self.task['obligation'])
        candidates = []
        for identity,record in self.graph['modules'].items():
            shared = {mode:sorted(set(gaps[mode]) & set(record.get(mode,[]))) for mode in ('read','write')}
            if any(shared.values()):
                candidates.append({'id':identity,'implementation':record['implementation'],**shared})
        candidates.sort(key=lambda item:-(len(item['read'])+len(item['write'])))
        return {'coverage_gaps':gaps,'possible_module_owners':candidates[:4],
            'repair_target':'design_metadata',
            'instruction':'Check actual direct effects and called modules against the source. Add only real callee links '
                'or source-backed effects using patch_capabilities. Candidates are hints, not proof of reuse. '
                'Do not modify correct code or rerun passing tests merely to fix a design declaration.'}

    def discard_draft(self, ids):
        if set(ids) & self.initial_ids:
            raise ValueError('Previously accepted capabilities cannot be discarded')
        changed = False
        for key in ids:
            for section in ('apis','modules'):
                changed = changed or key in self.graph[section]
                self.graph[section].pop(key,None)
            self.changed_capabilities.discard(key)
        self.completed = None
        if changed:
            self.revision += 1
        self.persist(self.graph)
        return {'discarded_draft_ids':ids,'instruction':'Remove stale references/unused draft registrations in your current design and implementation; prior callers remain protected.'}

    def get_capabilities(self, ids):
        records = {}
        for identity,record in closure(self.graph, ids).items():
            digest = hashlib.sha256(json.dumps(record,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if self.capability_observations.get(identity) == digest:
                records[identity] = {'cached':True,'context_reference':'Earlier get_capabilities['+identity+']',
                    'sha256':digest}
            else:
                records[identity] = deepcopy(record)
                self.capability_observations[identity] = digest
        return records

    def retrieve_schema(self, names):
        provided = self.task.get('provided_schema',{})
        return {'entities':{name:self.schema['entities'][name] for name in names if name in self.schema['entities'] and name not in provided},
            'already_supplied':{name:'Initial provided_schema['+name+']' for name in names if name in provided},
            'missing':[name for name in names if name not in self.schema['entities']]}

    def search_capabilities(self, query):
        cache_id = hashlib.sha256((query + ':' + str(self.revision)).encode()).hexdigest()[:12]
        if cache_id in self.retrieval_cache:
            return {'cached':True,'cache_id':cache_id,'context_reference':'Earlier search_capabilities result with this cache_id in the retained conversation'}
        result = self.retriever.retrieve(query, self.task['obligation'], self.accepted_graph)
        self.retrieval_cache[cache_id] = result
        return {'cache_id':cache_id, **result}

    def begin_tests(self):
        if self.phase != 'design':
            raise ValueError('Design is already completed; continue tests or TDD in this retained context')
        if not self.associated:
            raise ValueError('Associate the current requirement first, including [] for genuinely empty roots')
        refresh_graph(self.graph, self.schema)
        if not roots(self.graph, self.rid):
            raise ValueError('Use skip_backend for an evidenced backend-free requirement, or define its internal capabilities')
        for identity, record in closure(self.graph,roots(self.graph,self.rid)).items():
            if record['description'].strip().lower() in {'placeholder','todo','tbd'} or re.search(r'\s',record['name']):
                raise ValueError(f'{identity}: provide a real responsibility and callable function name before implementation')
        self.phase = 'tests'
        owners = [record['implementation'] for record in closure(self.graph, roots(self.graph,self.rid)).values()]
        self.files.files.update(owners)
        self.files.preferred_files.update(owners)
        self.tools = {tool.name:tool for tool in self.build_tools()}
        targets = {}
        for role in ('registry','test_path'):
            path = self.task[role]
            target = self.files.path(path)
            exists = target.is_file()
            targets[role] = {'path':path,'exists':exists,
                'initial_operation':('append' if target.stat().st_size == 0 else 'replace') if exists else 'create',
                'context_reference':'Initial landing_files or earlier read_file; read only if content is missing/changed.'}
        return {'phase':self.phase,'design_completed':True,
            'design_reference':'Earlier saved upsert/patch calls in this conversation; get_capabilities for a named missing contract.',
            'design_feedback':self.design_feedback(),'implementation_targets':targets,
            'test_mechanics_reference':'Initial test_mechanics_reference; no need to reread the runner.',
            'next_action':'Write source tests, then begin_tdd (automatically observes initial RED).'}

    def require_dependency(self, name, version, reason):
        if self.phase == 'design':
            raise ValueError('Complete design and begin_tests before declaring concrete test/implementation libraries')
        if not re.fullmatch(r'(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+',name) or not re.fullmatch(r'[~^]?\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?',version) or not reason.strip():
            raise ValueError('Supply an npm registry name, explicit semver version/range, and a concrete source implementation reason')
        from infrastructure.utils.files import save_json
        path = self.files.path('backend/package.json')
        package = json.loads(path.read_text(encoding='utf-8-sig'))
        if package.get('dependencies',{}).get(name) != version:
            package.setdefault('dependencies',{})[name] = version
            save_json(path,package)
            self.pending_dependencies = True
        return {'dependency':name,'version':version,'note':'Host installs dependencies before the next real acceptance check'}

    def skip_backend(self, reason):
        if not reason.strip() or any(self.task['obligation'].get(mode,[]) for mode in ('read','write')):
            raise ValueError('Cannot skip nonempty DB behavior; supply a source-based backend-free reason')
        if self.changed_capabilities:
            raise ValueError('Proposed capability changes must be implemented, not published by skipping')
        self.associate([],[])
        self.completed = {'status':'GREEN','backend_disposition':'frontend_or_container_only','reason':reason}
        return self.completed

    def repair_test_mechanics(self, reason, source_refs):
        if self.require_build:
            raise ValueError('Final integration keeps all accepted suites readonly; repair source code')
        if not reason.strip() or not source_refs:
            raise ValueError('Cite the observed CURRENT-suite mechanics error and source expectations to preserve')
        self.test_repairs += 1
        self.allow_test_repair = True
        self.tests_frozen = False
        return {'editable_test':self.task['test_path'],
            'instruction':'Use write_test for the evidenced mechanics correction, preserving every source assertion. There is no separate repair quota.'}

    def change_repair_strategy(self, diagnosis, evidence, actions):
        if not diagnosis.strip() or not evidence or not actions or any(not isinstance(v,str) or not v.strip() for v in [*evidence,*actions]):
            raise ValueError('Provide a concrete diagnosis, observed evidence and different repair actions')
        key = failure_signature({'failure':self.last_failure_signature,'diagnosis':diagnosis,
            'evidence':evidence,'actions':actions})
        if key in self.strategies:
            return {'already_recorded':True,'next_action':'This diagnosis/actions already occurred; implement a genuinely different repair or report a concrete blocker.'}
        self.strategies.add(key)
        self.same_failures = 0
        if self.last_failure_signature:
            self.failure_counts[self.last_failure_signature] = 0
        return {'strategy_recorded':True,'budget':self.budget.state(),
            'instruction':'Apply the concrete source repair now. The single TDD iteration budget is unchanged.'}

    def report_blocker(self, reason, evidence):
        if not reason.strip() or not evidence:
            raise ValueError('Report the concrete unresolved gap and observed evidence, not a generic inability to continue')
        self.blocker = {'reason':reason,'evidence':evidence}
        return {'status':'BLOCKED','blocker':self.blocker}

    def _failed(self, feedback):
        self.last_feedback = compact_feedback(feedback)
        def normalize_locations(value):
            if isinstance(value,dict):
                return {key:normalize_locations(child) for key,child in value.items()}
            if isinstance(value,list):
                return [normalize_locations(child) for child in value]
            if isinstance(value,str):
                value = re.sub(r'(\.(?:tsx?|mjs|js)):\d+(?::\d+)?',r'\1:<location>',value)
                value = re.sub(r'((?:127\.0\.0\.1|localhost)):\d+',r'\1:<port>',value)
                return re.sub(r'(\.tsx?)\(\d+,\d+\)',r'\1(<location>)',value)
            return value
        signature = failure_signature(normalize_locations(feedback))
        self.failure_counts[signature] = self.failure_counts.get(signature,0) + 1
        self.same_failures = self.failure_counts[signature]
        self.last_failure_signature = signature
        return {'status':'NEEDS_REPAIR','feedback':self.last_feedback,
            'same_error_count':self.same_failures,'strategy_change_recommended':self.same_failures >= 3,
            'budget':self.budget.state(),'test_assertions_frozen':self.tests_frozen,
            'next_action':('Correct source-backed design fields/callee links with patch_capabilities, then finish_requirement. '
                'Do not edit correct source or rerun passing tests for a metadata-only gap.'
                if feedback.get('repair_target') == 'design_metadata' else
                'Call change_repair_strategy with a new evidence-based diagnosis/actions, or report_blocker.'
                if self.same_failures >= 3 else 'Repair the specific source cause, then finish_requirement; do not repeat unchanged checks.')}

    @staticmethod
    def verification_feedback(result):
        """Keep complete checks in node reports; avoid replaying passing TAP to the model."""
        result = dict(result)
        if 'checks' in result:
            result['checks'] = {kind:({key:value for key,value in check.items() if key in
                {'returncode','tests','pass','fail','skipped','todo','reused_unchanged_sources'}}
                if isinstance(check,dict) and check.get('returncode') == 0 else compact_feedback(check))
                for kind,check in result['checks'].items()}
        return result

    def _observation_state(self):
        return (self.acceptance_fingerprint() if self.acceptance_fingerprint else self.code_revision,self.require_build)

    def write_test(self, operation, new_content, old_content=''):
        if self.phase != 'tests' and not self.allow_test_repair:
            raise ValueError('Tests are retained during TDD; use repair_test_mechanics only for an evidenced current-suite defect')
        arguments = {'path':self.task['test_path'],'operation':operation,'new_content':new_content}
        if old_content:
            arguments['old_content'] = old_content
        result = execute_native_file(self.files,'edit_file',arguments)
        if isinstance(result,dict) and result.get('status') == 'NEEDS_REPAIR':
            feedback = result.get('feedback',{})
            feedback['tool_name'] = 'write_test'
            if 'message' in feedback:
                feedback['message'] = feedback['message'].replace('native edit_file','native write_test')
            feedback.get('example_arguments',{}).pop('path',None)
        if any(change['before'] != change['after'] for change in self.files.last_changes):
            self.code_revision += 1
            self.completed = None
            if self.phase == 'implementation':
                # One evidenced correction can need several local edits. Close the
                # correction window at verification, not after the first edit.
                self.tests_frozen = False
        return result

    def run_tests(self):
        if self.phase == 'tests':
            path = self.files.path(self.task['test_path'])
            if not path.is_file() or not path.read_text(encoding='utf-8-sig').strip():
                return {'status':'WRITE_TESTS_FIRST','test_path':self.task['test_path']}
            state = self._observation_state()
            if state == self.baseline_state and self.baseline_result is not None:
                return {**self.baseline_result,'reused_unchanged_observation':True}
            if self.test_gate is None:
                raise ValueError('Host must provide the initial test observation callback')
            try:
                observation = self.test_gate(self)
                typed, tested = observation.get('typecheck') or {}, observation.get('tests') or {}
                green = (typed.get('returncode') == 0 and tested.get('returncode') == 0
                    and tested.get('pass',0) > 0 and not any(tested.get(k) for k in ('fail','skipped','todo')))
                result = {'status':'GREEN' if green else 'INITIAL_RED','checks':compact_feedback(observation)}
            except (ValueError,RuntimeError) as error:
                result = {'status':'INITIAL_RED','feedback':compact_feedback(getattr(error,'feedback',{'error':str(error)}))}
            self.baseline_state = self._observation_state()
            self.baseline_result = result
            return {**result,'counts_as_tdd_iteration':False,
                'next_action':'Refine test mechanics if necessary, then begin_tdd. Preserve source expectations; do not force RED for already-correct reused code.'}
        if self.phase != 'implementation':
            return {'status':'TESTS_REQUIRED','next_action':'Complete design, begin_tests, write source tests, then begin_tdd.'}
        self.allow_test_repair = False
        self.tests_frozen = True
        state = self._observation_state()
        if state == self.last_check_state and self.last_test_result is not None:
            observed = self.last_test_result
            if self.last_test_result.get('status') != 'GREEN':
                observed = self._failed(self.last_feedback or self.last_test_result.get('feedback',{}))
                if self.budget.test_iterations < self.budget.max_test_iterations:
                    self.budget.test_iterations += 1
                if self.budget.test_iterations >= self.budget.max_test_iterations:
                    self.stop_reason = 'TDD test/fix iteration limit reached'
            return {**self.verification_feedback(observed),'budget':self.budget.state(),'reused_unchanged_observation':True,
                'next_action':'Reuse this result. Change the actual source cause before rerunning failed acceptance, or finish_requirement when GREEN.'}
        if self.budget.test_iterations >= self.budget.max_test_iterations:
            self.stop_reason = 'TDD test/fix iteration limit reached'
            return {'status':'TEST_ITERATION_LIMIT','budget':self.budget.state(),'feedback':self.last_feedback}
        self.acceptance_attempted = False
        try:
            checks = self.gate(self)
            self.test_ok = True
            result = {'status':'GREEN','checks':checks}
        except (ValueError,RuntimeError) as error:
            self.test_ok = False
            result = self._failed(getattr(error,'feedback',{'error':str(error)}))
        self.budget.test_iterations += 1
        self.last_check_state = self._observation_state()
        self.last_test_result = result
        if not self.test_ok and self.budget.test_iterations >= self.budget.max_test_iterations:
            self.stop_reason = 'TDD test/fix iteration limit reached'
        result['budget'] = self.budget.state()
        return self.verification_feedback(result)

    def begin_tdd(self):
        if self.phase != 'tests':
            raise ValueError('Generate the current tests after design before beginning TDD')
        path = self.files.path(self.task['test_path'])
        if not path.is_file() or not path.read_text(encoding='utf-8-sig').strip():
            raise ValueError('Use write_test to create the current source-based suite first')
        already_observed = self.baseline_state == self._observation_state() and self.baseline_result is not None
        baseline = self.run_tests()
        self.phase = 'implementation'
        self.tests_frozen = True
        self.allow_test_repair = False
        self.tools = {tool.name:tool for tool in self.build_tools()}
        return {'phase':self.phase,'tests_retained':True,'initial_observation':
                {'status':baseline['status'],'context_reference':'Earlier run_tests observation; unchanged sources.'}
                if already_observed else baseline,
            'registry':self.task['registry'],'budget':self.budget.state(),
            'next_action':'Implement real sources with edit_file, then finish_requirement to verify and publish. '
                'Use run_tests only for intermediate diagnosis. Reads remain available when needed.'}

    def finish(self):
        self.completed = None
        if self.phase != 'implementation':
            return {'status':'TDD_REQUIRED','next_action':'Follow design -> begin_tests/write_test -> begin_tdd -> implementation/run_tests.'}
        try:
            refresh_graph(self.graph,self.schema)
            associated = [key for ids in self.graph['requirements'].values() for key in ids]
            associated += [key for ids in self.graph['requirement_modules'].values() for key in ids]
            unattached = self.changed_capabilities - closure(self.graph,associated).keys()
            if unattached:
                return self._failed({'unattached_capabilities':sorted(unattached),'instruction':'Connect real capabilities or discard unneeded drafts.'})
            gaps = coverage(self.graph,self.rid,self.task['obligation'])
            if any(gaps.values()):
                return self._failed(self.design_feedback())
            for identity,record in closure(self.graph,roots(self.graph,self.rid)).items():
                if not self.files.path(record['implementation']).is_file():
                    return self._failed({'error':f'{identity}: implement {record["implementation"]}'})
        except (ValueError,RuntimeError) as error:
            return self._failed({'error':str(error)})
        result = self.run_tests()
        if result.get('status') != 'GREEN':
            return result
        self.completed = {'status':'GREEN','phase':'implemented','checks':self.last_test_result['checks']}
        return self.verification_feedback(self.completed)

    def _exhausted(self, reason):
        error = AgentLoopExhausted(f'Backend {self.rid}: {reason}; node draft and logs retain diagnostics')
        error.turns = self.budget.calls
        error.feedback = {'last_failure':self.last_feedback,'budget':self.budget.state(),'blocker':self.blocker}
        return error

    def _loop(self, console):
        # No discovery/model-turn quotas: progress is guided by tool roles and soft
        # reminders. The sole stopping budget is implementation verification cycles.
        while True:
            self.tools = {tool.name:tool for tool in self.build_tools()}
            self.budget.calls += 1
            console.show(f'Backend {self.rid} | {self.phase} | model call {self.budget.calls}',
                json.dumps(self.budget.state(),ensure_ascii=False))
            try:
                message = self.step(tool_choice='auto')
            except (ValueError,IncompleteModelStreamError) as error:
                self.messages.append({'role':'user','content':str(error)+' Return a smaller complete native tool batch and advance the current workflow step.'})
                continue
            calls = message.tool_calls or []
            names = {call.function.name for call in calls}
            repeated = []
            for call in calls:
                if call.function.name in READ_TOOLS:
                    try:
                        arguments = json.loads(call.function.arguments)
                    except ValueError:
                        arguments = call.function.arguments
                    key = json.dumps([call.function.name,arguments,self.revision,self.code_revision],
                        ensure_ascii=False,sort_keys=True)
                    if key in self.read_observations:
                        repeated.append(call.function.name)
                    self.read_observations.add(key)
            if names & READ_TOOLS:
                self.budget.reads += 1
            self.read_streak = self.read_streak + 1 if names and names <= READ_TOOLS else 0
            before = (self.phase,self.code_revision,self.revision,self.associated,self.budget.test_iterations)
            results = self.execute_tools(message)
            after = (self.phase,self.code_revision,self.revision,self.associated,self.budget.test_iterations)
            self.no_progress_rounds = self.no_progress_rounds + 1 if before == after else 0
            for record in results:
                value = json.loads(record['content']).get('result')
                if isinstance(value,dict) and value.get('cached'):
                    repeated.append('cached lookup')
                if isinstance(value,list) and any(isinstance(item.get('result'),dict) and item['result'].get('cached') for item in value):
                    repeated.append('unchanged file/query')
            if self.blocker:
                raise self._exhausted('concrete blocker reported: '+self.blocker['reason'])
            if self.completed is not None and all(json.loads(record['content'])['ok'] for record in results):
                return {**self.completed,'turns':self.budget.calls,'budget':self.budget.state()}
            if self.stop_reason:
                raise self._exhausted(self.stop_reason)
            if repeated or self.read_streak >= 3 or self.no_progress_rounds >= 3:
                self.messages.append({'role':'user','content':json.dumps({'progress_reminder':{
                    'phase':self.phase,'repeated_reads':repeated,'consecutive_read_batches':self.read_streak,
                    'rounds_without_design_test_or_code_progress':self.no_progress_rounds,
                    'instruction':'Reuse retained evidence. Explain one precise missing fact if essential; otherwise advance design -> tests -> TDD source edits. Reading is still available; this is a soft progress reminder.'}},ensure_ascii=False)})
            if not calls:
                self.messages.append({'role':'user','content':'Advance the current step using its main native tools: design, write_test/begin_tdd, then edit_file/run_tests/finish_requirement.'})

    def run(self, input, console, max_test_iterations=None):
        if max_test_iterations is not None:
            if max_test_iterations < 1:
                raise ValueError('max_test_iterations must be positive')
            self.budget.max_test_iterations = max_test_iterations
        self.task = input
        self.start(input)
        return self._loop(console)

    def repair_integration(self, feedback, console):
        self.completed = None
        self.accepted_graph = deepcopy(self.graph)
        self.retrieval_cache.clear()
        self.require_build = True
        self.tests_frozen = True
        self.allow_test_repair = False
        self.messages.append({'role':'user','content':json.dumps({'final_integration_feedback':compact_feedback(feedback),
            'budget':self.budget.state(),'instruction':'Use the remaining SAME test/fix iterations to repair shared source/build failure; preserve accepted tests.'},ensure_ascii=False)})
        return self._loop(console)
