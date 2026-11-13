"""A leaf-local native agent: design, implementation and immutable source acceptance."""

from copy import deepcopy
import hashlib
import json
import os
import re

from infrastructure.shared.agent import BaseAgent, AgentTool, AgentLoopExhausted
from infrastructure.shared.agent.feedback import compact_feedback, failure_signature
from infrastructure.shared.agent.files import editable_application_path
from infrastructure.shared.agent.native_files import native_file_definition, execute_native_file
from infrastructure.shared.agent.outlines import collect_outline
from infrastructure.shared.models.streaming import IncompleteModelStreamError
from infrastructure.stages.frontend.arco import IMPLEMENT_INSTRUCTIONS as ARCO_RULES
from infrastructure.stages.frontend.arco import COMPONENTS
from infrastructure.stages.frontend.outline import normalize_items, implementation_path, DESIGN_EXAMPLE


STRINGS = {'type':'array','items':{'type':'string'}}
READ_TOOLS = {'read_file','list_files','search_files','get_backend_apis','get_ui_design','retrieve_schema'}

RULES = '''Complete ONE leaf requirement in this SAME conversation, in order:
1. DESIGN: read the supplied source scenarios/UI evidence and related backend inventory.
   Reuse accepted pages, shell and components. Call save_design with a SHORT description
   of pages/components, main actions/states, routes, API IDs and actual file locations.
   No component tree, trigger DSL or detailed UI contract. Then begin_implementation.
2. IMPLEMENT FIRST: inspect the supplied tests/helpers, then use edit_file for a complete
   initial version of real components, state, routing and HTTP integration. Reuse actual
   working owners. Implement first instead of running tests against absent pages.
3. ACCEPT AND REPAIR: finish_requirement runs matching EXISTING tests then publishes.
   A final pass regresses all supplied tests. run_tests diagnoses after implementation.
   Repair application code in this same conversation. No frontend tests are generated.

COMPONENT ORGANIZATION
App.tsx owns composition/routes, not every feature's markup, forms and business logic.
Split source-required pages into pages/<feature>/ or features/<feature>/; put substantial
tables, editor forms and dialogs into focused sibling component files. Reuse shared
shell/navigation/session, HTTP client, hooks and types from real existing owners.
Describe these file responsibilities in save_design before implementation. Extract when
responsibilities differ or reuse justifies it, not a mandatory file for every small JSX
fragment. Do not put the whole application into App.tsx or a giant component file; do not
create empty layers, a generated UI interpreter, or one file per button/trigger.
Keep original exports/callers and all accepted routes/behaviors working incrementally.

EVIDENCE AND REAL INTEGRATION
Source descriptions, scenarios, ancestor rules, UI states and screenshot analysis are
authority. Preserve explicit names, labels, roles and source routes; unspecified details
are your choice. Screenshots illustrate appearance, not runtime rows or preset data.
Backend APIs and database are already implemented. get_backend_apis batches exact
contracts for selected IDs before wiring requests. Inspect actual handlers only for a
named missing fact. Derive authentication/registration, user types, permissions and
workflow behavior from these actual contracts and source; never assume fixed auth URLs,
session bodies, identity tables or a generic registration template is compatible.
Do not modify backend, schema, DDL or startup seeds. If backend behavior is missing or
contradicts source, report a precise upstream blocker with endpoint/source evidence.
Never simulate success, store domain truth in localStorage, mock requests, hardcode fixture
identities, recognize test data, or preload When/Then results into page/test state.

Implement the entire user event -> input/selected ID -> real HTTP -> response -> visible
state path. Use actual row identity, parameterized routes and direct/reload/back navigation
as required. Browser cookies are browser-managed; never set Cookie or read HttpOnly tokens.
Use a shared client for actual CSRF/session/error conventions. Client permission controls
must match server behavior. Handle source-required loading/empty/error/denied, form
validation, workflow states and persistence after reload. Avoid stale async updates.
Choose ONE submission owner, e.g. Form.onSubmit. Do not post again in onClick or effects.
Maintain a per-operation pending flag; retries preserve actual protocol idempotency rules.
Do not add global request deduplication that suppresses legitimate separate operations.

SUPPLIED TESTS ARE READONLY
Source tests are copied byte-for-byte from input/tests. Their filenames (requirement IDs)
select acceptance, not generated SCN title patterns. Read task.source_test_paths and
source_test_root/support only for concrete observable requirements. Their actual imports,
helpers, login/menu flows, expectations and configuration are authoritative test inputs.
The runner starts the real local application on isolated ports with a new startup DB;
E2E_BASE_URL points at that local frontend. Source-defined setup/lifecycle stays unchanged.
Do not create, edit, skip, rewrite or weaken tests/helpers/config, add test-only code,
mock responses, inject When/Then outcomes, or change source seed data to trick assertions.
When no same-ID source test exists, implement the requirement and supporting shared
modules, then finish normally as GREEN. Do not generate substitutes or request test coverage.
Some supplied tests check only UI structure. Implement the full described business
behavior as well; passing those tests alone is not proof of every business scenario.
For a genuine test or backend defect, report the exact source/test evidence and blocker.

TOOLS AND PROGRESS
Read tools remain available throughout. Inspect enough evidence in one or two focused
batches, then act. Batch independent read/write calls in one response; execute verification
last. Reuse supplied startup/reference excerpts and cached results. Do not browse the whole
application or reread unchanged helpers. Repeated reads get soft progress reminders, not
hard discovery budgets. Only implementation verification/fix attempts have a budget
(default 10). Cached GREEN publication is free. Source tests are never regenerated.
Unchanged failed checks reuse diagnostics but count as retries. Repeated failures require
a different evidence-based strategy or report_blocker, not another identical check.
edit_file requires path/operation/new_content; create ONLY for absent files, otherwise
replace with unique exact old_content or append/prepend. No rename/new_path or wrappers.
All test paths are readonly. Successful tool calls remain
saved if another batch call fails: resend only the failed call with smaller valid JSON.
save_design updates small metadata during implementation when actual file/API choices
change; do not restart design or rewrite correct code merely for a metadata correction.
save_design example: {"items":{"page-example":{"purpose":"Source page actions",
"kind":"page","implementation_hint":"frontend/src/pages/ExamplePage.tsx","api_ids":[]}},
"uses":["page-example"],"notes":"Reuse actual shell/client"}.
items keys and uses are UI IDs, not field names, Arco components or filenames.
implementation_hint contains ONE filename; put explanations in purpose/notes.
After format feedback correct only the named fields using the supplied example, not
another full redesign. Reads have no new hard budget; report a concrete blocker when
you cannot resolve a specified gap instead of repeating the same invalid proposal.

NAVIGATION AND ACCESSIBILITY
Implement the real menu/link/dialog transitions expected by the existing source tests.
Source-required return destinations, reload and back/forward should work. Dialog-only
states need actual dialogs, not invented routes. Use actual source names and identities.
Reuse task.accessibility_reference; do not label both outer combobox and inner input
with the same name. Preserve prior shared helper imports/callers and cumulative behavior.
For large page expansion create focused new components and locally wire composition;
do not repeatedly submit rejected whole-file replacements. Never change tests to match
an inaccessible control or a disconnected page.

'''


class FrontendBuildAgent(BaseAgent):
    def __init__(self, plan, backend, schema, rid, files, gate, *,
            fingerprint, persist=None, on_phase=None, max_test_iterations=None, **options):
        super().__init__(**options)
        self.plan, self.backend, self.schema = deepcopy(plan), backend, schema
        self.initial_plan = deepcopy(plan)
        self.rid, self.files, self.gate = rid, files, gate
        self.fingerprint, self.persist = fingerprint, persist or (lambda plan:None)
        self.on_phase = on_phase or (lambda phase:None)
        self.logger.name = type(self).__name__+':'+rid
        self.phase, self.completed, self.blocker = 'design', None, None
        self.calls, self.read_batches, self.test_iterations = 0, 0, 0
        self.max_test_iterations = int(max_test_iterations if max_test_iterations is not None
            else os.getenv('FRONTEND_TEST_ITERATIONS','10'))
        if self.max_test_iterations < 1:
            raise ValueError('FRONTEND_TEST_ITERATIONS must be positive')
        self.revision, self.code_revision = 0, 0
        self.require_build = False
        self.last_check_state, self.last_test_result, self.last_feedback = None, None, None
        self.failure_counts, self.read_observations, self.contract_observations = {}, set(), {}
        self.stop_reason = None

    def budget(self):
        return {'model_calls':self.calls,'read_batches':self.read_batches,
            'test_iterations':self.test_iterations,'test_iteration_limit':self.max_test_iterations}

    def build_system_prompt(self):
        return RULES + ARCO_RULES.replace(
            'Do not add API mutations during stage 08; stage 10 extends the same component handlers.',
            'During implementation wire actual API mutations into the same components; there is no later trigger stage.')

    def build_user_prompt(self, input):
        return {**input,'agent_budget':self.budget()}

    def build_tools(self):
        tools = [
            AgentTool('save_design','items maps stable UI IDs to records; uses contains those same IDs, not filenames or Arco names. implementation_hint is ONE filename without commentary. Example: {"items":{"page-example":{"purpose":"Source actions","implementation_hint":"frontend/src/pages/ExamplePage.tsx"}},"uses":["page-example"],"notes":"reuse shell"}. No JSX/tree/DSL.',
                {'type':'object','properties':{'items':{'type':'object','additionalProperties':{'type':'object',
                    'properties':{'purpose':{'type':'string'},'kind':{'type':'string'},'route':{'type':'string'},
                        'implementation_hint':{'type':'string','description':'ONE frontend/src/ filename, e.g. frontend/src/pages/ExamplePage.tsx. No (existing), explanations or multiple paths.'},'api_ids':STRINGS,'depends_on':STRINGS,'states':STRINGS},
                    'required':['purpose','implementation_hint'],'additionalProperties':False}},
                    'uses':STRINGS,'notes':{'type':'string'}},'required':['items','uses','notes'],'additionalProperties':False},self.save_design),
            AgentTool('get_ui_design','Retrieve selected accepted/draft UI items in one batch; repeated unchanged items return references.',
                {'type':'object','properties':{'ids':STRINGS},'required':['ids'],'additionalProperties':False},self.get_ui_design),
            AgentTool('get_backend_apis','Batch selected API IDs to inspect exact real HTTP contracts before requests; no default platform endpoints.',
                {'type':'object','properties':{'ids':STRINGS},'required':['ids'],'additionalProperties':False},self.get_backend_apis),
            AgentTool('retrieve_schema','Read only named fixture tables missing from supplied schema.',
                {'type':'object','properties':{'names':STRINGS},'required':['names'],'additionalProperties':False},self.retrieve_schema),
            AgentTool('report_blocker','Report a precise evidenced upstream/environment/source blocker; ends only this leaf attempt.',
                {'type':'object','properties':{'reason':{'type':'string'},'evidence':STRINGS},
                    'required':['reason','evidence'],'additionalProperties':False},self.report_blocker)]
        for schema in self.files.schemas():
            name = schema['tool']
            if name not in {'read_file','list_files','search_files','edit_file'} or (name=='edit_file' and self.phase!='implementation'):
                continue
            description, parameters = native_file_definition(schema)
            def bind_file(selected):
                def invoke(**arguments):
                    if selected == 'edit_file' and '/tests/' in arguments.get('path',''):
                        raise ValueError('Supplied tests/support/config are readonly; repair application code')
                    return self.file_call(selected,arguments)
                return invoke
            tools.append(AgentTool(name,description,parameters,bind_file(name)))
        empty = {'type':'object','properties':{},'additionalProperties':False}
        if self.phase == 'design':
            tools += [AgentTool('begin_implementation','Finish lightweight design and implement an initial application version before running supplied tests.',empty,self.begin_implementation),
                AgentTool('skip_frontend','Exclude only source-backed non-browser behavior with NO supplied tests; cite evidence.',
                    {'type':'object','properties':{'reason':{'type':'string'},'source_refs':STRINGS},
                        'required':['reason','source_refs'],'additionalProperties':False},self.skip_frontend)]
        else:
            tools += [AgentTool('run_tests','After initial implementation, run the exact supplied tests and accepted regression. Tests are never editable.',empty,self.run_tests),
                AgentTool('finish_requirement','Accept the implementation using supplied readonly tests; reuse unchanged passing results.',empty,self.finish),
                AgentTool('require_dependency','Declare a necessary frontend npm library and semver; host installs before verification.',
                    {'type':'object','properties':{'name':{'type':'string'},'version':{'type':'string'},'reason':{'type':'string'}},
                        'required':['name','version','reason'],'additionalProperties':False},self.require_dependency)]
        return tools

    def save_design(self, items, uses, notes):
        items = normalize_items(items,self.rid,self.files.output)
        provided = deepcopy(items)
        items, uses, notes = collect_outline({'items':items,'uses':uses,'notes':notes},self.rid)
        for identity,item in items.items():
            earlier = self.plan['items'].get(identity,{})
            if identity in provided and 'api_ids' not in provided[identity] and 'api_ids' in earlier:
                item['api_ids'] = earlier['api_ids']
            items[identity] = {**earlier,**item}
        for identity,item in items.items():
            path = item.get('implementation_hint','')
            if not isinstance(path,str) or not path.startswith('frontend/src/') or not editable_application_path(self.files.output,path):
                raise ValueError(identity+': choose an editable frontend/src/ implementation location')
            self.files.path(path)  # Validate path safety, independent of the current phase.
        inventory = {**self.plan['items'],**items}
        warnings, external = [], []
        def resolve(reference):
            if reference in inventory:
                return reference
            if reference in COMPONENTS:
                external.append({'reference':reference,'kind':'arco_component'})
                return None
            try:
                path,_ = implementation_path(reference,self.files.output)
                matches = [key for key,item in inventory.items() if item.get('implementation_hint')==path]
                if len(matches)==1:
                    warnings.append({'reference':reference,'resolved_ui_id':matches[0]})
                    return matches[0]
                external.append({'reference':path,'kind':'source_file'})
            except ValueError:
                warnings.append({'reference':reference,'unresolved':True,
                    'instruction':'Use an actual UI ID or define it; this remains an explicit coordination gap, not new business scope.'})
            return None
        uses = list(dict.fromkeys(value for reference in uses if (value:=resolve(reference)) is not None))
        for item in items.values():
            item['depends_on'] = list(dict.fromkeys(value for reference in item.get('depends_on',[]) if (value:=resolve(reference)) is not None))
        before = json.dumps(self.plan,sort_keys=True,ensure_ascii=False)
        self.plan['items'].update(items)
        self.plan['requirements'][self.rid] = uses
        self.plan['notes'][self.rid] = notes
        self.plan.setdefault('reference_diagnostics',{})[self.rid] = {'resolutions':warnings,'external_references':external}
        if before != json.dumps(self.plan,sort_keys=True,ensure_ascii=False):
            self.revision += 1
            self.completed = None
        self.persist(self.plan)
        return {'saved':list(items),'uses':uses,'reference_diagnostics':warnings,'external_references':external,
            'next_action':'Design is retained. Resolve source-relevant missing links as needed, then begin_implementation; do not resubmit unrelated records.'}

    def retained_records(self, kind, records):
        result = {}
        for identity,record in records.items():
            digest = hashlib.sha256(json.dumps(record,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            key = (kind,identity)
            result[identity] = ({'cached':True,'context_reference':'Earlier '+kind+'['+identity+']'}
                if self.contract_observations.get(key) == digest else deepcopy(record))
            self.contract_observations[key] = digest
        return result

    def get_ui_design(self, ids):
        return self.retained_records('get_ui_design',{key:self.plan['items'][key] for key in ids if key in self.plan['items']})

    def get_backend_apis(self, ids):
        records = {key:{k:v for k,v in self.backend['apis'][key].items() if k!='usage'}
            for key in ids if key in self.backend['apis']}
        return {'apis':self.retained_records('get_backend_apis',records),'missing':sorted(set(ids)-records.keys())}

    def retrieve_schema(self, names):
        supplied = self.task.get('provided_schema',{})
        return {'entities':{name:self.schema['entities'][name] for name in names if name in self.schema['entities'] and name not in supplied},
            'already_supplied':[name for name in names if name in supplied],
            'missing':[name for name in names if name not in self.schema['entities']]}

    def begin_implementation(self):
        if self.phase != 'design' or self.rid not in self.plan['requirements']:
            raise ValueError('Save the lightweight design first')
        self.phase = 'implementation'
        self.on_phase(self.phase)
        self.tools = {tool.name:tool for tool in self.build_tools()}
        return {'phase':self.phase,'source_test_paths':self.task['source_test_paths'],
            'next_action':'Implement a complete initial version with edit_file, then finish_requirement. Do not write tests.'}

    def file_call(self, name, arguments):
        result = execute_native_file(self.files,name,arguments)
        if name=='edit_file' and any(c['before']!=c['after'] for c in self.files.last_changes):
            self.code_revision += 1
            self.completed = None
        return result

    def require_dependency(self, name, version, reason):
        from infrastructure.utils.files import save_json
        if not re.fullmatch(r'(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+',name) or not re.fullmatch(r'[~^]?\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?',version) or not reason.strip():
            raise ValueError('Supply an npm library, explicit semver and source-based reason')
        path = self.files.output/'frontend/package.json'
        package = json.loads(path.read_text(encoding='utf-8-sig'))
        package.setdefault('dependencies',{})[name] = version
        save_json(path,package)
        self.pending_dependencies = True
        return {'dependency':name,'version':version,'note':'Host installs before verification.'}

    def report_blocker(self, reason, evidence):
        if not reason.strip() or not evidence:
            raise ValueError('Supply a precise blocker with observed source/endpoint/error evidence')
        self.blocker = {'reason':reason,'evidence':evidence}
        return {'status':'BLOCKED','blocker':self.blocker}

    def skip_frontend(self, reason, source_refs):
        if not reason.strip() or not source_refs:
            raise ValueError('Explain and cite why no source browser behavior belongs to this leaf')
        if self.task.get('source_test_paths'):
            raise ValueError('This requirement has supplied browser tests and cannot be skipped')
        self.plan = deepcopy(self.initial_plan)
        self.plan['requirements'][self.rid] = []
        self.plan['notes'][self.rid] = reason
        self.persist(self.plan)
        self.completed = {'status':'NO_UI','error':reason,'source_refs':source_refs}
        return self.completed

    @staticmethod
    def verification_feedback(result):
        result = dict(result)
        if 'checks' in result:
            result['checks'] = {kind:({key:value for key,value in check.items() if key in
                {'returncode','passed','failed','skipped','flaky','reused_unchanged_sources'}}
                if isinstance(check,dict) and check.get('returncode')==0 else compact_feedback(check))
                for kind,check in result['checks'].items()}
        return result

    def failed(self, feedback):
        self.last_feedback = compact_feedback(feedback)
        def normalize(value):
            if isinstance(value,dict):
                return {key:normalize(child) for key,child in value.items()}
            if isinstance(value,list):
                return [normalize(child) for child in value]
            if isinstance(value,str):
                value = re.sub(r'((?:127\.0\.0\.1|localhost)):\d+',r'\1:<port>',value)
                value = re.sub(r'(\.(?:tsx?|mjs|js)):\d+(?::\d+)?',r'\1:<location>',value)
                return re.sub(r'(\.tsx?)\(\d+,\d+\)',r'\1(<location>)',value)
            return value
        signature = failure_signature(normalize(feedback))
        self.failure_counts[signature] = self.failure_counts.get(signature,0)+1
        count = self.failure_counts[signature]
        return {'status':'NEEDS_REPAIR','feedback':self.last_feedback,'same_error_count':count,
            'budget':self.budget(),'strategy_change_recommended':count>=3,
            'next_action':('Change repair strategy using this evidence or report a precise blocker.' if count>=3 else
                'Repair the specific source/interaction cause. For a genuine source-test defect report the exact blocker; never edit tests. Do not repeat unchanged verification.')}

    def run_tests(self):
        state = (self.fingerprint(),self.require_build)
        if self.phase!='implementation':
            return {'status':'DESIGN_REQUIRED','next_action':'save_design then begin_implementation, implement first, then verify'}
        if state==self.last_check_state and self.last_test_result is not None:
            result = self.last_test_result
            if result['status']!='GREEN':
                self.test_iterations += 1
                result = self.failed(self.last_feedback or result)
                if self.test_iterations>=self.max_test_iterations:
                    self.stop_reason = 'TDD test/fix iteration limit reached'
            return {**self.verification_feedback(result),'reused_unchanged_observation':True}
        if self.test_iterations>=self.max_test_iterations:
            self.stop_reason = 'TDD test/fix iteration limit reached'
            return {'status':'TEST_ITERATION_LIMIT','budget':self.budget()}
        self.test_iterations += 1
        try:
            result = {'status':'GREEN','checks':self.gate(self)}
        except (ValueError,RuntimeError) as error:
            result = self.failed(getattr(error,'feedback',{'error':str(error)}))
        self.last_check_state, self.last_test_result = (self.fingerprint(),self.require_build), result
        if result['status']!='GREEN' and self.test_iterations>=self.max_test_iterations:
            self.stop_reason = 'TDD test/fix iteration limit reached'
        return {**self.verification_feedback(result),'budget':self.budget()}

    def finish(self):
        self.completed = None
        result = self.run_tests()
        if result.get('status')=='GREEN':
            self.completed = {'status':'GREEN','checks':self.last_test_result['checks'],'phase':'implemented'}
            return self.verification_feedback(self.completed)
        return result

    def tool_error_feedback(self, call, error):
        result = super().tool_error_feedback(call,error)
        if call.function.name=='save_design':
            result.update(getattr(error,'feedback',{'example_arguments':deepcopy(DESIGN_EXAMPLE)}))
            result['known_ui_ids'] = list(self.plan['items'])[:20]

        return result

    def exhausted(self, reason):
        error = AgentLoopExhausted('Frontend '+self.rid+': '+reason)
        error.turns = self.calls
        error.feedback = {'budget':self.budget(),'last_failure':self.last_feedback,'blocker':self.blocker}
        return error

    def loop(self, console):
        no_progress = 0
        while True:
            self.tools = {tool.name:tool for tool in self.build_tools()}
            self.calls += 1
            console.show(f'Frontend {self.rid} | {self.phase} | model call {self.calls}',json.dumps(self.budget()))
            try:
                message = self.step(tool_choice='auto')
            except (ValueError,IncompleteModelStreamError) as error:
                self.messages.append({'role':'user','content':str(error)+' Return a smaller complete native tool batch and advance the current step.'})
                continue
            calls = message.tool_calls or []
            names, repeated = {call.function.name for call in calls}, []
            for call in calls:
                if call.function.name in READ_TOOLS:
                    try:
                        arguments = json.loads(call.function.arguments)
                    except ValueError:
                        arguments = call.function.arguments
                    key = json.dumps([call.function.name,arguments,self.revision,self.code_revision],sort_keys=True,ensure_ascii=False)
                    if key in self.read_observations:
                        repeated.append(call.function.name)
                    self.read_observations.add(key)
            self.read_batches += int(bool(names & READ_TOOLS))
            before = (self.phase,self.revision,self.code_revision,self.test_iterations)
            results = self.execute_tools(message)
            no_progress = no_progress+1 if before==(self.phase,self.revision,self.code_revision,self.test_iterations) else 0
            if self.blocker:
                raise self.exhausted(self.blocker['reason'])
            if self.completed is not None and all(json.loads(record['content'])['ok'] for record in results):
                return {**self.completed,'turns':self.calls,'budget':self.budget()}
            if self.stop_reason:
                raise self.exhausted(self.stop_reason)
            if repeated or no_progress>=3 or not calls:
                self.messages.append({'role':'user','content':json.dumps({'progress_reminder':{
                    'phase':self.phase,'repeated_reads':repeated,'rounds_without_progress':no_progress,
                    'instruction':'Reuse retained evidence. Name one precise missing fact or advance design -> initial implementation -> supplied-test acceptance. Reading remains available.'}},ensure_ascii=False)})

    def run(self, input, console):
        self.task = input
        self.pending_dependencies = False
        self.start(input)
        return self.loop(console)

    def repair_integration(self, feedback, console):
        self.require_build, self.completed = True, None
        self.messages.append({'role':'user','content':json.dumps({'final_integration_feedback':compact_feedback(feedback),
            'instruction':'Repair frontend build/integration using the remaining SAME iteration budget. All accepted suites and backend are readonly.'},ensure_ascii=False)})
        return self.loop(console)
