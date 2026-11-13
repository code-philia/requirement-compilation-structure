"""One leaf traversal: design, initial implementation, supplied-test acceptance."""

from copy import deepcopy
import hashlib
import json

from infrastructure.shared.agent.files import editable_application_path
from infrastructure.shared.agent.feedback import CheckFailure
from infrastructure.shared.agent.incremental import RequirementCheckpoints
from infrastructure.shared.agent.recovery import implementation_task
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.models.text import TextModel
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.shared.project.preparation import prepare_with_recovery
from infrastructure.shared.rag.bm25 import rank
from infrastructure.stages.backend.context import requirement_schema
from infrastructure.stages.frontend.arco import arco_references, stack_context, PROVIDER_PATH, validate_component_types
from infrastructure.stages.frontend.arco_knowledge import retrieve_components, record_retrieval
from infrastructure.stages.frontend.build_agent import FrontendBuildAgent
from infrastructure.stages.frontend.check_cache import FrontendCheckCache
from infrastructure.stages.frontend.outline import normalize_plan_paths, implementation_path
from infrastructure.stages.frontend.context import load_frontend_context
from infrastructure.stages.frontend.triggers.acceptance import original_requirements
from infrastructure.stages.frontend.triggers.e2e_runtime import CONFIG, VITE_CONFIG
from infrastructure.stages.frontend.source_tests import SourceTests, SourceE2EChecks, prepare_source_e2e, ROOT as SOURCE_TEST_ROOT
from infrastructure.stages.frontend.verification import verify_frontend, require_stable_acceptance
from infrastructure.stages.frontend.ui.runtime import APPLICATION_ENTRYPOINTS, prepare_frontend
from infrastructure.stages.requirements.acceptance import test_accounts
from infrastructure.utils.files import read_artifact, save_json
from infrastructure.utils.presentation.console import DemoConsole


STAGE = '06_build_frontend'


def selected_design(plan, rid):
    selected, pending = {}, list(plan.get('requirements',{}).get(rid,[]))
    while pending:
        identity = pending.pop()
        if identity in selected or identity not in plan['items']:
            continue
        record = plan['items'][identity]
        selected[identity] = record
        pending.extend(record.get('depends_on',[]))
    return selected


def publish_plan(arc_dir, plan):
    cleaned = normalize_plan_paths(plan,arc_dir.parent)
    plan.clear()
    plan.update(cleaned)
    locations, missing = {}, []
    for key,item in plan['items'].items():
        try:
            path,_ = implementation_path(item.get('implementation_hint'),arc_dir.parent)
            if (arc_dir.parent/path).is_file():
                locations[key] = path
            else:
                missing.append({'id':key,'path':path,'reason':'No implemented file at this design hint'})
        except (ValueError,OSError) as error:
            missing.append({'id':key,'reason':str(error)})
    plan['missing_implementation_hints'] = missing
    save_json(arc_dir/'frontend_plan.json',plan)
    save_json(arc_dir/'frontend_implementation_files.json',locations)


def build_frontend(input_dir, arc_dir, pause=False, max_test_iterations=None):
    output = arc_dir.parent.resolve()
    _, schema, backend, images, contexts = load_frontend_context(arc_dir,input_dir)
    tree = original_requirements(input_dir)
    raw = read_artifact(arc_dir,'requirements.json')
    order = list(tree.leaves)
    catalog = SourceTests(input_dir,output,order)
    console = DemoConsole(pause)
    runtime = {}
    def bind_checks():
        runtime['checks'] = SourceE2EChecks(output,catalog)
    preparation = prepare_with_recovery(arc_dir,[
        ('node_runtime',bind_checks),
        ('frontend_runtime',lambda:prepare_frontend(output)),
        ('source_test_runtime',lambda:prepare_source_e2e(output,backend,catalog,arc_dir)),
        ('dependencies',lambda:install_dependencies(output)),
        ('arco_types',lambda:validate_component_types(output)),
        ('chromium',lambda:runtime['checks'].install_browser() if catalog.specs else None)],console,report_name='frontend_preparation.json')
    if preparation['status']!='GREEN':
        report = {'status':'FAILED','error':preparation['error'],'requirements':{},
            'preparation':preparation,'verification':{'environment':preparation},
            'recovery':'Fix the recorded environment step, then resume '+STAGE+'. Accepted code and earlier stage artifacts are retained.'}
        save_json(arc_dir/'frontend_e2e.json',report)
        return report
    cached = FrontendCheckCache(output,runtime['checks'])
    previous = read_artifact(arc_dir,'frontend_e2e.json') if (arc_dir/'frontend_e2e.json').is_file() else {}
    plan = read_artifact(arc_dir,'frontend_plan.json') if (arc_dir/'frontend_plan.json').is_file() else {
        'kind':'frontend','items':{},'requirements':{},'notes':{}}
    plan = normalize_plan_paths(plan,output)
    plan.update(architecture='native_leaf_implement_source_tests',status='IMPLEMENTING')
    report = {'status':'IMPLEMENTING','architecture':'native_leaf_implement_source_tests','order':order,
        'requirements':{},'tests':{},'preparation':preparation,'source_tests':catalog.manifest}
    # Existing source, UI evidence and actual endpoint changes all invalidate stale
    # acceptance. Source import associations protect unrelated accepted pages.
    resume = RequirementCheckpoints(arc_dir,'frontend',raw,lambda rid:{
        'version':'native_frontend_v3_supplied_tests','source_tests':catalog.fingerprints(rid),'schema':schema,
        'backend':backend,'source_context':contexts[rid],'design':selected_design(plan,rid)})
    references = arco_references()
    if (output/'reference').is_dir():
        references['references/source'] = output/'reference'
    accepted, last_agent = [], None
    dependency_paths = ('frontend/package.json','package-lock.json','npm-shrinkwrap.json','frontend/package-lock.json')
    fixture_paths = [CONFIG,VITE_CONFIG,'frontend/src/components/accessibility.tsx',*catalog.files]
    for rid in order:
        test_paths = catalog.bindings[rid]
        reused = resume.reuse(rid)
        if reused:
            report['requirements'][rid] = reused
            accepted.append(rid)
            report['tests'][rid] = test_paths
            console.show('Frontend | Reuse '+rid,'Implementation and supplied test evidence are unchanged; cumulative acceptance remains enabled.')
            continue
        entry = report['requirements'][rid] = {'status':'DESIGNING','requirements':[rid],'test_paths':test_paths}
        if test_paths:
            entry['test_path'] = test_paths[0]
        save_json(arc_dir/'frontend_e2e.json',report)
        agent = None
        with implementation_task(output,entry,console,'Frontend design/implementation/source acceptance '+rid,extra_paths=dependency_paths):
            holder = {}
            def writable(path, _holder=holder):
                owner = _holder['agent']
                return owner.phase=='implementation' and path.startswith('frontend/src/') and editable_application_path(output,path)
            files = FileTools(output,['frontend','backend'],requirements=[rid],stage='frontend',
                discovery=True,references=references,files=[*APPLICATION_ENTRYPOINTS,PROVIDER_PATH,*test_paths],allow_write=writable)
            current = catalog.selected([rid])
            def ensure_dependencies(owner):
                if owner.pending_dependencies:
                    install_dependencies(output)
                    owner.pending_dependencies = False
            def acceptance(owner, _current=tuple(current)):
                ensure_dependencies(owner)
                catalog.verify()
                selected = catalog.specs if owner.require_build else list(_current)
                result = {'typecheck':cached.typecheck(selected)}
                if result['typecheck']['returncode']:
                    raise CheckFailure('Frontend source/test compilation failed',result)
                result['e2e'] = cached.tests(selected) if selected else None
                if selected:
                    try:
                        require_stable_acceptance(result['e2e'])
                    except ValueError as error:
                        raise CheckFailure('Supplied source-test acceptance or cumulative regression failed',result) from error
                if owner.require_build:
                    result['build'] = cached.build()
                    if result['build']['returncode']:
                        raise CheckFailure('Final application build failed',result)
                return result
            draft_path = arc_dir/'frontend_node_drafts'/(hashlib.sha256(rid.encode()).hexdigest()[:20]+'.json')
            def publish_phase(phase, _entry=entry):
                _entry['status'] = {'implementation':'IMPLEMENTING'}.get(phase,'DESIGNING')
                save_json(arc_dir/'frontend_e2e.json',report)
            agent = FrontendBuildAgent(plan,backend,schema,rid,files,acceptance,
                fingerprint=cached.fingerprint,model=TextModel(json_mode=False),max_test_iterations=max_test_iterations,
                on_phase=publish_phase,
                persist=lambda value,_path=draft_path:save_json(_path,value))
            holder['agent'] = agent
            query = json.dumps({key:contexts[rid].get(key) for key in ('name','description','steps')},ensure_ascii=False)
            matches = rank(query,{key:json.dumps(item,ensure_ascii=False) for key,item in plan['items'].items()},6)
            related = set(plan['requirements'].get(rid,[])) | {match['symbol'] for match in matches}
            ancestors, parent = [], tree.parents.get(rid)
            while parent:
                ancestors.append(tree.requirements[parent])
                parent = tree.parents.get(parent)
            components = retrieve_components(contexts[rid])
            record_retrieval(arc_dir,STAGE,rid,components)
            task = {'requirement':contexts[rid], 'source_test_paths':test_paths,'source_test_root':SOURCE_TEST_ROOT,
                'source_test_support':[path for path in catalog.files if '/support/' in path],
                'ancestor_rules':list(reversed(ancestors)),
                'ui_candidates':{key:plan['items'][key] for key in sorted(related) if key in plan['items']},
                'backend_inventory':{key:{field:api[field] for field in ('description','signature','implementation') if field in api}
                    for key,api in backend['apis'].items()},
                'related_api_ids':backend.get('requirements',{}).get(rid,[]),
                'provided_schema':requirement_schema(schema,rid),
                'schema_inventory':{name:list(entity['fields']) for name,entity in schema['entities'].items()},
                'frontend_stack':stack_context(),'component_knowledge':components,
                'test_accounts':test_accounts(raw),
                'application_entrypoints':list(APPLICATION_ENTRYPOINTS),
                'previous_failure':{key:previous.get('requirements',{}).get(rid,{}).get(key) for key in ('error','feedback','archive')}}
            task['accessibility_reference'] = {'path':'frontend/src/components/accessibility.tsx',
                'usage':'Import selectAriaLabel/requiredLabel from the shared helper. Spread selectAriaLabel(originalLabel) '
                    'on Arco Select; do not add a second input/label association. Preserve this helper across features.'}
            task['landing_files'] = {}
            for path in [*APPLICATION_ENTRYPOINTS,PROVIDER_PATH,'frontend/src/components/accessibility.tsx']:
                target = output/path
                content = target.read_text(encoding='utf-8-sig') if target.is_file() else None
                task['landing_files'][path] = {'exists':content is not None,
                    'content':content if content is not None and len(content)<=4000 else None}
                if content is not None and len(content)<=4000:
                    files.supplied_contents[path] = content
            files.supplied_content_references = {path:'Initial landing_files['+path+'].content'
                for path,record in task['landing_files'].items() if isinstance(record['content'],str)}
            entry.update(agent.run(task,console))
            if entry['status']=='NO_UI':
                entry.pop('test_path',None)
            else:
                entry.update(verification_scope='supplied_source_tests' if test_paths else 'implementation',
                    passed=(entry['checks'].get('e2e') or {}).get('passed',0))
        if entry['status'] in {'GREEN','NO_UI'}:
            plan = agent.plan
            publish_plan(arc_dir,plan)
            if entry['status']!='NO_UI':
                accepted.append(rid)
                report['tests'][rid] = test_paths
                last_agent = agent
                resume.accept(rid,entry,[*catalog.bindings[rid],*fixture_paths,
                    *[item['implementation_hint'] for item in selected_design(plan,rid).values()
                        if item.get('implementation_hint') and (output/item['implementation_hint']).is_file()]])
        save_json(arc_dir/'frontend_e2e.json',report)
    integrated = {'typecheck':cached.typecheck(catalog.specs)}
    if integrated['typecheck']['returncode']==0 and catalog.specs:
        integrated['e2e'] = cached.tests(catalog.specs)
    integrated['build'] = cached.build()
    integration_failed = any(value.get('returncode') for value in integrated.values())
    if integrated.get('e2e'):
        try:
            require_stable_acceptance(integrated['e2e'])
        except ValueError:
            integration_failed = True
    if integration_failed and last_agent is not None:
        last_agent.plan = deepcopy(plan)
        repair = report['integration_repair'] = {'status':'IMPLEMENTING','requirements':[last_agent.rid]}
        with implementation_task(output,repair,console,'Frontend integration repair in retained context',extra_paths=dependency_paths):
            last_agent.repair_integration(integrated,console)
            repair['status'] = 'GREEN'
            plan = last_agent.plan
            publish_plan(arc_dir,plan)
    plan['status'] = 'COMPLETED_WITH_FAILURES' if any(entry['status']=='FAILED' for entry in report['requirements'].values()) else 'GREEN'
    publish_plan(arc_dir,plan)
    # Keep the established frontend_e2e report and dashboard acceptance translation.
    ui = {'outline':True,'pages':plan['items'],'requirements':plan['requirements'],'notes':plan['notes']}
    report['incremental'] = {'checkpoint':resume.path.name,'reused_requirements':sum(
        bool(entry.get('reused_checkpoint')) for entry in report['requirements'].values())}
    report['check_cache'] = cached.stats
    final = verify_frontend(arc_dir,tree,backend,ui,console,report,checks=cached,source_tests=catalog)
    if final['status']=='GREEN':
        resume.refresh_accepted(report['requirements'],lambda key:[*catalog.bindings[key],*fixture_paths,
            *[item['implementation_hint'] for item in selected_design(plan,key).values()
                if item.get('implementation_hint') and (output/item['implementation_hint']).is_file()]])
    return final
