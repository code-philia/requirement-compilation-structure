"""Source-driven startup evidence collection and schema reconciliation before SQL."""

from copy import deepcopy
import hashlib
import json

from infrastructure.shared.agent import AgentTool
from infrastructure.stages.database.design_agent import DatabaseDesignAgent, SCHEMA_RULES
from infrastructure.utils.files import read_artifact, save_json


PLAN = 'db_startup_plan.json'
VERSION = 2


class SchemaRepairRequested(RuntimeError):
    requires_schema_repair = True

    def __init__(self, request):
        self.request = request
        super().__init__('Database implementation needs source-backed schema reconciliation: '+request['reason'])


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def nodes(raw):
    result = {}
    def visit(node):
        result[node['id']] = node
        for child in node.get('children',[]) or []:
            visit(child)
    visit(raw)
    return result


def explicit_records(raw):
    """Collect real data lists throughout the document; data.requires is not a record."""
    result = {}
    for rid,node in nodes(raw).items():
        data = node.get('data',[])
        if not isinstance(data,list):
            continue
        for row in data:
            if not isinstance(row,dict) or not {'id','entity','properties','lifecycle'} <= row.keys():
                raise ValueError(rid+': each explicit data entry needs id/entity/properties/lifecycle')
            if row['id'] in result and result[row['id']] != row:
                raise ValueError('Conflicting explicit data ID: '+row['id'])
            result[row['id']] = deepcopy(row)
    return result


def startup_context(raw):
    return {key:row for key,row in explicit_records(raw).items() if row['lifecycle']=='SEED'}


def model_seed_context(records, max_chars=16000):
    """Small bundles stay verbatim; large bundles are reviewed separately in data batches."""
    if len(json.dumps(records,ensure_ascii=False))<=max_chars:
        return records
    groups = {}
    for row in records.values():
        group = groups.setdefault(row['entity'],{'count':0,'properties':set(),'example_ids':[]})
        group['count'] += 1
        group['properties'].update(row.get('properties',{}))
        if len(group['example_ids'])<3:
            group['example_ids'].append(row['id'])
    return {'summary_only':True,'entities':{name:{**group,'properties':sorted(group['properties'])} for name,group in groups.items()},
        'policy':'All actual values are reviewed in dedicated data batches before SQL; do not invent omitted values.'}


def data_batches(records, max_records=24, max_chars=16000):
    batch, size = {}, 0
    for key,row in records.items():
        count = len(json.dumps(row,ensure_ascii=False))
        if batch and (len(batch)>=max_records or size+count>max_chars):
            yield batch
            batch, size = {}, 0
        batch[key] = row; size += count
    if batch:
        yield batch


def effective_requirements(raw, arc_dir):
    """Keep the original document immutable; add only current, source-cited startup facts."""
    result = deepcopy(raw)
    records = explicit_records(raw)
    path = arc_dir/PLAN
    if path.is_file():
        plan = read_artifact(arc_dir,PLAN)
        if plan.get('version')==VERSION and plan.get('source_sha256')==digest(raw) and plan.get('status')=='GREEN':
            for key,row in plan.get('derived_records',{}).items():
                if key in records and records[key] != row:
                    raise ValueError('Derived startup data cannot replace source data: '+key)
                records[key] = row
    result['data'] = list(records.values())
    return result


RULES = '''Collect source-required startup facts and reconcile the logical DB schema.
You have the original explicit data lists, source authorization catalog and a batch of
requirements. Explicit SEED records are mandatory, including every account credential,
role and unit binding. Their existence is evidence even when ER omits identity tables.
No table/column names or identity architecture are preset. Use upsert_entity to repair
the smallest coherent model: a credential must have a persisted secure-hash location;
roles may use code rows/junctions or source-compatible constraints. Preserve ALL source
role codes, including administrator bindings; never substitute employee/supervisor labels
or narrow an enum to exclude catalog/seed values. Business categories are not auth roles.
Do not copy passwords as schema defaults, invent accounts/grants, or grant everyone admin.
For account seeds inspect the actual credential, role and membership definitions, not
just their column-name inventory. A field name is not proof that its CHECK accepts the
source value. Retrieve these related definitions in one batch before publishing review.

For EACH requirement in this batch judge whether it explicitly requires startup data.
Fixed dictionaries/options, initial configuration and specifically declared default rows
can be startup facts. Ordinary Given examples, screenshot rows, records users create,
future transactions/approvals, aggregates computed later and CREATED/DERIVED data are NOT
startup facts. A default field value alone need not create a row. Do not infer business
seed records merely to make later tests pass. Link presets to an exact quote from that
requirement's description/data, not a hypothetical scenario Given. Preserve literals.
If prose does not determine initial values, record why no startup row is justified.

Submit one decision for every batch requirement (none is valid with a reason). Submit
only NEW source-backed preset records; the host retains explicit records unchanged.
Reuse earlier preset identities rather than inventing duplicate shared rows. Use stable
symbolic $ref IDs for named explicit data, and record assumptions only for technical keys.
Ensure the canonical schema can store these facts before finishing. Repair missing fields,
FK parents and incompatible scalar constraints rather than omitting data. Entity updates
merge existing fields; preserve previous obligations, entities and legitimate constraints.
Batch reads/updates. No SQL here, no repeated full-schema discovery. Retrieve named tables
only when their full definition is missing. source_data is global even for child nodes.
'''


class StartupPlanningAgent(DatabaseDesignAgent):
    completion_tool_name = 'publish_startup_batch'

    def __init__(self, schema, sources, plan, raw, **options):
        super().__init__(schema,sources,mode='startup',**options)
        self.plan, self.raw = plan, raw

    def build_system_prompt(self):
        return SCHEMA_RULES+'\n'+RULES

    def build_tools(self):
        tools = [tool for tool in super().build_tools() if tool.name in {'retrieve_entity','upsert_entity'}]
        tools.append(AgentTool('publish_startup_batch','Publish a source-data decision for EVERY supplied requirement and only explicit prose presets. Finish after schema repairs.',
            {'type':'object','properties':{'decisions':{'type':'object','additionalProperties':{'type':'object','properties':{
                'disposition':{'type':'string','enum':['none','explicit_data','preset_required','runtime_only']},
                'reason':{'type':'string'}},'required':['disposition','reason'],'additionalProperties':False}},
                'records':{'type':'array','items':{'type':'object','properties':{
                    'id':{'type':'string'},'entity':{'type':'string'},'properties':{'type':'object','additionalProperties':True},
                    'source_requirement':{'type':'string'},'source_quote':{'type':'string'}},
                    'required':['entity','properties','source_requirement','source_quote'],'additionalProperties':False}},
                'affected_requirements':{'type':'array','items':{'type':'string'}},'summary':{'type':'string'}},
             'required':['decisions','records','affected_requirements','summary'],'additionalProperties':False},self.publish_batch))
        return tools

    def publish_batch(self, decisions, records, affected_requirements, summary):
        self.ensure_complete()
        expected = {node['id'] for node in self.input['requirements']}
        if set(decisions)!=expected or any(not item.get('reason') for item in decisions.values()):
            raise ValueError('Give one source-backed decision for every supplied requirement ID: '+', '.join(sorted(expected)))
        all_nodes = nodes(self.raw)
        if set(affected_requirements)-all_nodes.keys():
            raise ValueError('Affected obligation IDs must be actual requirement IDs')
        added = {}
        for row in records:
            rid = row['source_requirement']
            allowed = expected | {parent['id'] for node in self.input['requirements'] for parent in node.get('parent_context',[])}
            if rid not in allowed:
                raise ValueError('Preset must cite a requirement or its parent context in this batch')
            source = all_nodes[rid]
            description = source.get('description','')
            if isinstance(description,dict):
                description = str(description.get('text',''))+'\n'+json.dumps(description,ensure_ascii=False)
            # Explicit record lists were collected already; quoting them again must
            # not turn CREATED data or a second copy of an account into a new preset.
            data = source.get('data',{})
            text = str(description)+'\n'+(json.dumps(data,ensure_ascii=False) if isinstance(data,dict) else '')
            if not row['source_quote'].strip() or row['source_quote'] not in text:
                raise ValueError('Preset needs an exact description/data quote from '+rid+' (not a scenario Given)')
            identity = row.get('id') or 'DATA-PRESET-'+digest([rid,row['entity'],row['properties']])[:16]
            record = {'id':identity,'lifecycle':'SEED','entity':row['entity'],'properties':row['properties'],
                'requirements':[rid],'source_refs':[rid],'source_quote':row['source_quote']}
            earlier = self.plan['explicit_records'].get(identity) or self.plan['derived_records'].get(identity)
            if earlier is not None and earlier != record:
                raise ValueError('Preserve existing startup record; do not replace '+identity)
            added[identity] = record
        self.plan['derived_records'].update(added)
        self.plan['requirements'].update(decisions)
        self.completed = {'summary':summary,'affected_requirements':affected_requirements,'records':list(added)}
        return {'status':'COMPLETE','added_records':list(added),'schema_entities':len(self.schema['entities'])}


class DatabaseBatchAgent(StartupPlanningAgent):
    """One context handles schema repairs, startup decisions and all batch effects."""
    completion_tool_name = 'submit_database_batch'

    def build_system_prompt(self):
        from infrastructure.stages.database.design_agent import OBLIGATION_RULES
        rules = OBLIGATION_RULES.replace('submit_obligations', 'submit_database_batch')
        return SCHEMA_RULES+'\n'+RULES+'\n'+rules+"""
Analyze EVERY supplied leaf in one pass: (1) repair schema where evidence requires,
(2) distinguish source-required startup rows from runtime-created records,
(3) submit each leaf's own requirement and scenario-step obligations.
Parent context constrains leaves; do not copy unrelated sibling effects. Parent-owned
preset evidence may be cited via parent_context; do not duplicate an existing preset.
Batch entity retrieval and use provided definitions. Finish once with
submit_database_batch; no SQL and no separate startup-planning loop.
"""

    def build_tools(self):
        from infrastructure.stages.database.design_agent import RECORD
        base = super().build_tools()
        parameters = deepcopy(base[-1].parameters)
        parameters['properties']['obligations'] = {'type':'object','additionalProperties':{
            'type':'object','properties':{'requirement':RECORD,
                'steps':{'type':'object','additionalProperties':RECORD}},
            'required':['requirement','steps'],'additionalProperties':False}}
        parameters['required'].append('obligations')
        return base[:-1]+[AgentTool(self.completion_tool_name,
            'Publish all batch schema repairs, startup decisions and requirement/step effects together.',
            parameters,self.submit_database_batch)]

    def submit_database_batch(self, decisions, records, affected_requirements, summary, obligations):
        from infrastructure.stages.database.obligations.records import normalize_record, check_symbols
        expected = {node['id']:node for node in self.input['requirements']}
        if set(obligations)!=set(expected):
            raise ValueError('Include exactly the supplied requirement IDs: '+', '.join(expected))
        normalized = {}
        for rid,node in expected.items():
            entry = obligations[rid]
            if set(entry['steps'])!={step['id'] for step in node['steps']}:
                raise ValueError('Include exactly the supplied step IDs for '+rid)
            result = {'requirement':normalize_record(entry['requirement']),
                'steps':{key:normalize_record(value) for key,value in entry['steps'].items()}}
            for mode in ('read','write','observation_read'):
                result['requirement'][mode] = sorted(set(result['requirement'].get(mode,[])) |
                    {field for record in result['steps'].values() for field in record.get(mode,[])})
            check_symbols([result['requirement'],*result['steps'].values()],self.schema)
            normalized[rid] = result
        response = super().publish_batch(decisions,records,affected_requirements,summary)
        self.completed['obligations'] = normalized
        return response


def analysis_batches(tree, selected=None, max_nodes=5, max_chars=32000):
    """Dependency ordered leaves, full own steps, inherited evidence, bounded batches."""
    batch, size = [], 0
    for rid in tree.leaves:
        if selected is not None and rid not in selected:
            continue
        node = deepcopy(tree.raw[rid])
        node.pop('children',None)
        node['steps'] = [tree.steps[key] for key in tree.own_steps[rid]]
        node.pop('scenarios',None)  # normalized steps already carry scenario labels
        ancestors, parent = [], tree.parents.get(rid)
        while parent:
            source = tree.raw[parent]
            ancestors.append({key:source[key] for key in ('id','name','description','data') if key in source})
            parent = tree.parents.get(parent)
        node['parent_context'] = ancestors
        count = len(json.dumps(node,ensure_ascii=False))
        if batch and (len(batch)>=max_nodes or size+count>max_chars):
            yield batch
            batch,size = [],0
        batch.append(node); size += count
    if batch:
        yield batch


def plan_startup_data(arc_dir, raw, schema, *, model=None, console=None, force=False, repair=None, max_turns=24):
    fingerprint = digest(raw)
    evidence = read_artifact(arc_dir,'backend_evidence.json') if (arc_dir/'backend_evidence.json').is_file() else {}
    catalog = evidence.get('authorization',{}).get('catalog',{})
    previous = read_artifact(arc_dir,PLAN) if (arc_dir/PLAN).is_file() else {}
    reusable = (previous.get('version')==VERSION and previous.get('source_sha256')==fingerprint
        and previous.get('authorization_sha256')==digest(catalog))
    plan = previous if reusable else {'version':VERSION,'source_sha256':fingerprint,
        'authorization_sha256':digest(catalog),'explicit_records':explicit_records(raw),'derived_records':{},'requirements':{},'batches':{}}
    if not force and reusable and plan.get('status')=='GREEN' and plan.get('schema_sha256')==digest(schema['entities']):
        return plan
    if reusable and plan.get('status')=='GREEN' and repair is None:
        repair = {'reason':'Schema changed since source startup evidence was collected. Reconcile retained SEED facts, credentials and role constraints without rescanning requirements.',
            'source_refs':[]}
    plan['status'] = 'RUNNING'
    save_json(arc_dir/PLAN,plan)
    affected = set()
    # A schema repair reuses collected decisions; only inspect cited requirements.
    context = model_seed_context(plan['explicit_records'])
    if repair:
        known = nodes(raw)
        cited = [rid for rid in repair.get('source_refs',[]) if rid in known]
        review = [{key:known[rid][key] for key in ('id','name','description') if key in known[rid]} for rid in cited]
        review_records = {**plan['explicit_records'],**plan['derived_records']}
        batches = [(review,chunk) for chunk in data_batches(review_records)] or [(review,{})]
    else:
        # Requirement prose was analyzed jointly in stage03. Legacy/direct stage04
        # can reconcile explicit rows, but cannot silently repeat all requirements.
        batches = [([],chunk) for chunk in data_batches(plan['explicit_records'])] or [([],{})]
    for index,(batch,source_data) in enumerate(batches,1):
        key = digest({'requirements':[node['id'] for node in batch],'data_ids':list(source_data)})
        if not force and not repair and reusable and plan.get('batches',{}).get(key,{}).get('status')=='GREEN':
            continue
        if console:
            console.show('Database startup | Evidence batch '+str(index)+'/'+str(len(batches)),
                'Reconcile explicit data and source-required presets with logical tables before INSERT SQL.')
        agent = StartupPlanningAgent(schema,{},plan,raw,model=model,persist=lambda:save_json(arc_dir/'db_schema.json',schema))
        result = agent.run({'requirements':batch,'source_data':source_data,
            'known_presets':model_seed_context(plan['derived_records']),'source_authorization_catalog':catalog,
            'schema_repair_request':repair,'requirement_inventory':{rid:node.get('name','') for rid,node in nodes(raw).items()}},max_turns=max_turns)
        affected.update(result['affected_requirements'])
        if repair:
            plan['last_reconciliation'] = {'request':repair,'summary':result['summary']}
        plan.setdefault('batches',{})[key] = {'status':'GREEN','summary':result['summary']}
        save_json(arc_dir/PLAN,plan)
    plan.update(status='GREEN',schema_sha256=digest(schema['entities']),affected_requirements=sorted(affected))
    save_json(arc_dir/PLAN,plan)
    save_json(arc_dir/'db_schema.json',schema)
    return plan


def reconcile_startup_schema(arc_dir, schema, *, model, console, request=None, max_turns=24):
    """Repair design, then re-infer affected effects so backend consumers see new fields."""
    from infrastructure.stages.requirements.tree import RequirementTree
    from infrastructure.stages.requirements.data import compile_data
    from infrastructure.stages.database.obligations.records import check_symbols
    raw = read_artifact(arc_dir,'requirements.json')
    before = deepcopy(schema['entities'])
    plan = plan_startup_data(arc_dir,raw,schema,model=model,console=console,
        force=bool(request),repair=request,max_turns=max_turns)
    changed = {name for name in before.keys() | schema['entities'].keys() if before.get(name)!=schema['entities'].get(name)}
    affected = set(plan.get('affected_requirements',[])) if changed else set()
    related = set(changed)
    for name in changed:
        for field in schema['entities'].get(name,{}).get('fields',{}).values():
            if field.get('references'):
                related.add(field['references'].split('.',1)[0])
    affected.update(rid for rid,fields in schema.get('requirements',{}).items()
        if any(symbol.split('.',1)[0] in related for symbol in fields))
    obligation_path = arc_dir/'db_obligations.json'
    if affected and obligation_path.is_file():
        obligations = read_artifact(arc_dir,obligation_path.name)
        tree = RequirementTree(raw)
        evidence = read_artifact(arc_dir,'backend_evidence.json') if (arc_dir/'backend_evidence.json').is_file() else {}
        for batch in analysis_batches(tree,affected):
            ids = [node['id'] for node in batch]
            console.show('Database schema repair | Refresh batch '+', '.join(ids),
                'Update affected effects and startup evidence together; preserve unrelated requirements.')
            agent = DatabaseBatchAgent(schema,{},plan,raw,model=model,
                persist=lambda:save_json(arc_dir/'db_schema.json',schema))
            inferred = agent.run({'requirements':batch,
                'source_data':model_seed_context(plan['explicit_records']),
                'known_presets':model_seed_context(plan['derived_records']),
                'source_authorization_catalog':evidence.get('authorization',{}).get('catalog',{}),
                'schema_repair_request':request,
                'provided_entities':{name:schema['entities'][name] for name in related if name in schema['entities']}},
                max_turns=max_turns)
            for rid,result in inferred['obligations'].items():
                obligations['requirements'][rid] = result['requirement']
                obligations['steps'].update(result['steps'])
                schema['requirements'][rid] = sorted({field for mode in ('read','write','observation_read')
                    for field in result['requirement'].get(mode,[])})
            save_json(obligation_path,obligations)
            plan['schema_sha256'] = digest(schema['entities'])
            save_json(arc_dir/PLAN,plan)
        check_symbols([*obligations['requirements'].values(),*obligations.get('steps',{}).values()],schema)
    save_json(arc_dir/'db_schema.json',schema)
    if (arc_dir/'db_analysis.json').is_file():
        analysis = read_artifact(arc_dir,'db_analysis.json')
        analysis['schema_sha256'] = digest(schema['entities'])
        save_json(arc_dir/'db_analysis.json',analysis)
    save_json(arc_dir/'data_bindings.json',compile_data(effective_requirements(raw,arc_dir),schema))
    return {'changed_entities':sorted(changed),'refreshed_requirements':sorted(affected),'request':request}
