"""One traversal: hybrid retrieval, node-local design and implementation in one agent."""

from copy import deepcopy
import hashlib
import json

from infrastructure.shared.agent.files import editable_application_path
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.incremental import RequirementCheckpoints, digest
from infrastructure.shared.agent.recovery import implementation_task, final_checks, complete_report
from infrastructure.shared.agent.feedback import CheckFailure
from infrastructure.shared.models.text import TextModel
from infrastructure.shared.rag.backend import BackendRetriever
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.stages.backend.build_agent import BackendBuildAgent
from infrastructure.stages.backend.graph import empty_graph, refresh_graph, publish_graph, roots, closure
from infrastructure.stages.backend.context import load_context, requirement_context
from infrastructure.stages.backend.implementation_context import source_context, evidence_filename
from infrastructure.stages.backend.foundation import design_backend_foundation
from infrastructure.stages.backend.modules import publish_registries, AGGREGATOR, ROOT
from infrastructure.stages.backend.runtime import prepare_runtime, TEST_SUPPORT_PATH
from infrastructure.stages.backend.testing import BackendChecks, require_green
from infrastructure.stages.backend.check_cache import BackendCheckCache
from infrastructure.stages.requirements.acceptance import source_expectations, test_accounts, require_scenario_coverage
from infrastructure.utils.files import read_artifact, save_json
from infrastructure.utils.presentation.console import DemoConsole


STAGE = 'build_backend'


def traversal(tree):
    """Implement dependency-ordered leaves only; ancestor rules remain context."""
    return list(tree.leaves)


def implementation_inputs(graph, schema, obligations, rid):
    records = closure(graph, roots(graph,rid))
    return {'version':'native_joint_backend_v3_design_tests_tdd', 'schema':schema['entities'],
        'obligation':obligations['requirements'].get(rid,{}),
        'capabilities':{key:{k:v for k,v in record.items() if k not in {'callers','status'}} for key,record in records.items()} or {'source_backend':True}}


def startup_references(output, registry):
    """Supply small stable landing points once, without dumping the application."""
    files = {}
    for relative in (registry,'backend/src/api/types.ts',TEST_SUPPORT_PATH):
        path = output / relative
        if not path.is_file():
            files[relative] = {'exists':False}
            continue
        source = path.read_text(encoding='utf-8-sig')
        files[relative] = {'exists':True,'content':source if len(source) <= 4000 else None,
            'content_omitted':len(source) > 4000}
    return files


def build_backend(arc_dir, pause=False, max_test_iterations=None, top_k=6):
    output = arc_dir.parent.resolve()
    # Evidence publication only; this no longer supplies a preset identity platform.
    design_backend_foundation(output, arc_dir, pause=pause)
    tree, schema = load_context(arc_dir)
    raw = read_artifact(arc_dir,'requirements.json')
    obligations = read_artifact(arc_dir,'db_obligations.json')
    order = traversal(tree)
    missing = set(order) - obligations['requirements'].keys()
    if missing:
        raise ValueError('Missing requirement obligations; finish stage 03 for: ' + ', '.join(sorted(missing)))
    prepare_runtime(output)
    groups = [{'id':'requirement-'+hashlib.sha256(rid.encode()).hexdigest()[:12],
        'owner':rid,'requirements':[rid]} for rid in order]
    for group in groups:
        group['registry'] = f"backend/src/api/modules/{group['id']}/register.ts"
    # Previously accepted shared owners may have been registered by an ancestor
    # in older outputs. Keep their code reachable without creating parent tasks.
    existing_groups = read_artifact(arc_dir,'backend_modules.json').get('groups',[]) if (arc_dir/'backend_modules.json').is_file() else []
    current_ids = {group['id'] for group in groups}
    retained_groups = [group for group in existing_groups if group.get('id') not in current_ids
        and isinstance(group.get('registry'),str) and (output/group['registry']).is_file()]
    if not publish_registries(output,[*retained_groups,*groups]):
        raise ValueError('Backend registrar could not connect to the actual application entrypoint')
    install_dependencies(output)
    console = DemoConsole(pause)
    checks = BackendChecks(output)
    cached = BackendCheckCache(output,checks)
    graph_path = arc_dir / 'backend_graph.json'
    graph = read_artifact(arc_dir,graph_path.name) if graph_path.is_file() else empty_graph()
    refresh_graph(graph,schema)
    publish_graph(arc_dir,graph)
    report = {'mode':'source_implementation','architecture':'native_joint_backend','status':'IMPLEMENTING',
        'requirements':{},'tests':{},'retrieval':{},'order':order}
    previous = read_artifact(arc_dir,'backend_tdd.json') if (arc_dir/'backend_tdd.json').is_file() else {}
    resume = RequirementCheckpoints(arc_dir,'backend',raw,
        lambda rid: implementation_inputs(graph,schema,obligations,rid))
    reference_root = arc_dir/'source_context'
    for rid in tree.requirements:
        save_json(reference_root/evidence_filename(rid), requirement_context(tree,rid))
    references = {'references/context':reference_root}
    if (output/'reference').is_dir():
        references['references/source'] = output/'reference'
    accepted, accepted_oracles = [], []
    last_agent = None
    for rid, group in zip(order,groups):
        required = obligations['requirements'][rid]
        test_path = f"backend/tests/requirements/{hashlib.sha256(rid.encode()).hexdigest()[:20]}.test.ts"
        oracle = source_expectations(raw,rid)
        reused = resume.reuse(rid)
        if reused:
            report['requirements'][rid] = reused
            if reused.get('test_path'):
                accepted.append(reused['test_path'])
                accepted_oracles.append(oracle)
                report['tests'][rid] = {rid:reused['test_path']}
            console.show('Backend | Reuse '+rid,'Accepted source, graph and implementation files are unchanged; cumulative acceptance remains enabled.')
            continue
        entry = report['requirements'][rid] = {'status':'DESIGNING','requirements':[rid], 'test_path':test_path}
        query = '\n'.join([tree.requirements[rid]['name'],tree.requirements[rid]['description'],tree.concatenated_steps(rid)])
        retrieved = BackendRetriever().retrieve(query,required,graph,top_k)
        report['retrieval'][rid] = retrieved['matches']
        console.show('Backend retrieval | '+rid, json.dumps(retrieved['matches'],ensure_ascii=False))
        agent = None
        dependency_paths = ('backend/package.json','package-lock.json','npm-shrinkwrap.json','backend/package-lock.json')
        with implementation_task(output,entry,console,'Backend design and implementation '+rid,extra_paths=dependency_paths):
            owners = [record['implementation'] for record in [*retrieved['apis'].values(),*retrieved['modules'].values(),*retrieved['caller_context'].values()]]
            schema_names = {field.split('.',1)[0] for mode in ('read','write') for field in required.get(mode,[])}
            # Full schemas for this requirement only. Supporting tables remain
            # discoverable through retrieve_schema after choosing reuse candidates.
            landing = [group['registry'],'backend/src/api/types.ts',TEST_SUPPORT_PATH,*owners,
                *[f'backend/src/db/tables/{name}.sql' for name in sorted(schema_names)],test_path]
            holder = {}
            def writable(path, _test_path=test_path, _holder=holder):
                if path == _test_path:
                    return _holder['agent'].phase == 'tests' or _holder['agent'].allow_test_repair
                return (_holder['agent'].phase == 'implementation' and path.startswith('backend/src/')
                    and path not in {AGGREGATOR,ROOT,'backend/src/api/endpoints.json'} and editable_application_path(output,path))
            files = FileTools(output,['backend'],requirements=[rid],stage='backend',discovery=True,
                files=[p for p in landing if p==test_path or (output/p).is_file()],allow_write=writable,references=references)
            files.preferred_files = set(landing)
            files.defer_context_files = True
            current_paths = [*accepted,test_path]
            current_oracles = [*accepted_oracles,oracle]
            def observe_initial_tests(agent, _paths=tuple(current_paths), _oracles=tuple(current_oracles)):
                if agent.pending_dependencies:
                    install_dependencies(output)
                    agent.pending_dependencies = False
                typed = cached.run('typecheck',list(_paths))
                if typed['returncode']:
                    return {'typecheck':typed,'tests':None}
                tested = cached.run('tests',list(_paths))
                if tested['returncode'] == 0:
                    for expectation in _oracles:
                        require_scenario_coverage(tested,expectation)
                return {'typecheck':typed,'tests':tested}
            def acceptance(agent, _paths=tuple(current_paths), _oracles=tuple(current_oracles)):
                if agent.pending_dependencies:
                    install_dependencies(output)
                    agent.pending_dependencies = False
                for identity,record in closure(agent.graph,roots(agent.graph,agent.rid)).items():
                    if not (output/record['implementation']).is_file():
                        raise ValueError(f'{identity}: implement the declared source file {record["implementation"]}')
                selected_paths = list(accepted) if agent.require_build else list(_paths)
                expected = list(accepted_oracles) if agent.require_build else list(_oracles)
                agent.acceptance_attempted = True
                typed = cached.run('typecheck',selected_paths)
                agent.acceptance_attempted = not typed.get('reused_unchanged_sources',False)
                if typed['returncode']:
                    raise CheckFailure('Backend/shared caller compilation failed',typed)
                agent.tests_frozen = True
                typed_was_executed = agent.acceptance_attempted
                agent.acceptance_attempted = True
                tested = cached.run('tests',selected_paths)
                agent.acceptance_attempted = typed_was_executed or not tested.get('reused_unchanged_sources',False)
                require_green(tested)
                for expectation in expected:
                    require_scenario_coverage(tested,expectation)
                result = {'typecheck':typed,'tests':tested}
                if agent.require_build:
                    agent.acceptance_attempted = True
                    result['build'] = checks.build()
                    if result['build']['returncode']:
                        raise CheckFailure('Final backend build failed',result['build'])
                return result
            draft_path = arc_dir/'backend_node_drafts'/(hashlib.sha256(rid.encode()).hexdigest()[:20]+'.json')
            agent = BackendBuildAgent(graph,schema,rid,files,acceptance,model=TextModel(json_mode=False),
                acceptance_fingerprint=cached.fingerprint,test_gate=observe_initial_tests,
                persist=lambda value, _path=draft_path, _rid=rid:save_json(_path,{'requirement':_rid,'phase':'draft','graph':value}))
            holder['agent'] = agent
            context = source_context(tree,rid)
            context.pop('db_obligation',None)
            ancestors, parent = [], tree.parents.get(rid)
            while parent:
                ancestors.append(tree.requirements[parent])
                parent = tree.parents.get(parent)
            task = {'requirement':context, 'obligation':required,
                'ancestor_rules':list(reversed(ancestors)),
                'retrieved':retrieved, 'provided_schema':{name:schema['entities'][name] for name in sorted(schema_names)},
                'schema_inventory':{name:{'description':entity['description'],'fields':list(entity['fields'])} for name,entity in schema['entities'].items()},
                'registry':group['registry'],'test_path':test_path,'support_module':TEST_SUPPORT_PATH,
                'test_accounts':test_accounts(raw),
                'previous_failure':{key:previous.get('requirements',{}).get(rid,{}).get(key) for key in ('error','feedback','archive')}}
            task['landing_files'] = startup_references(output,group['registry'])
            task['test_mechanics_reference'] = {
                'support_module':TEST_SUPPORT_PATH,
                'contract':'The supplied context.ts is the actual compiler-owned runner contract. createApiTest(t) '
                    'returns {database,baseURL} for the real server and isolated initialized database; t.after closes '
                    'the client. fixturePasswordHash(password) encodes compatible Given credentials. '
                    'Do not launch a server or create When/Then outcomes in fixtures.',
                'optional_helpers_path':'backend/tests/support/helpers.ts',
                'optional_helpers_policy':'Use helper implementations only if their exact transport/schema contract '
                    'matches this source application. No assumed login route, Cookie/CSRF contract, identity table '
                    'or fixed fixture behavior. Read only the named missing helper if needed.',
                'typed_sql_example':'const row = database.prepare(sql).get(...bindings) as { count: number } | undefined; '
                    'assert.ok(row); assert.equal(row.count, expected); // Supply actual SQL, shape and source expectation.'}
            for path,record in task['landing_files'].items():
                if isinstance(record.get('content'),str):
                    files.supplied_contents[path] = record['content']
            files.supplied_content_references = {path:'Initial landing_files['+path+'].content'
                for path,record in task['landing_files'].items() if isinstance(record.get('content'),str)}
            result = agent.run(task,console,max_test_iterations=max_test_iterations)
            entry.update(result)
            if result.get('backend_disposition'):
                entry.pop('test_path',None)
            else:
                entry['implemented_capabilities'] = roots(agent.graph,rid)
        if entry['status']=='GREEN':
            graph = agent.graph
            refresh_graph(graph,schema)
            publish_graph(arc_dir,graph)
            if entry.get('test_path'):
                accepted.append(test_path)
                accepted_oracles.append(oracle)
                report['tests'][rid] = {rid:test_path}
                last_agent = agent
                # Shared graph/files can advance only after cumulative regression.
                resume.refresh_accepted(report['requirements'],lambda key:[report['requirements'][key]['test_path']]
                    if report['requirements'][key].get('test_path') else [])
            else:
                resume.accept(rid,entry,[])
        save_json(arc_dir/'backend_tdd.json',report)
    built = None
    if accepted:
        built = checks.build()
        if built['returncode'] and last_agent is not None:
            last_agent.graph = deepcopy(graph)
            repair = report['integration_repair'] = {'status':'IMPLEMENTING','requirements':[last_agent.rid]}
            with implementation_task(output,repair,console,'Backend integration repair in retained node context',extra_paths=dependency_paths):
                last_agent.repair_integration(built,console)
                graph = last_agent.graph
                refresh_graph(graph,schema)
                publish_graph(arc_dir,graph)
                repair['status']='GREEN'
            built = last_agent.completed['checks']['build'] if repair['status']=='GREEN' else None
    verification = final_checks(console,
        typecheck=(lambda:cached.run('typecheck',accepted),None),
        tests=(lambda:cached.run('tests',accepted),require_green if accepted else None),
        build=(lambda:built if built is not None else checks.build(),None))
    if all(item['status']=='GREEN' for item in verification.values()):
        resume.refresh_accepted(report['requirements'],lambda rid:[report['requirements'][rid]['test_path']]
            if report['requirements'][rid].get('test_path') else [])
    publish_graph(arc_dir,graph)
    report['check_cache'] = cached.stats
    report['usable_artifacts'] = {'backend_endpoints': bool(graph['apis'])
        and verification.get('typecheck',{}).get('status') == 'GREEN'
        and verification.get('build',{}).get('status') == 'GREEN'}
    complete_report(report,report['requirements'].values(),verification)
    save_json(arc_dir/'backend_tdd.json',report)
    return report
