"""One dependency-ordered leaf traversal: design, source tests, native UI TDD."""

from copy import deepcopy
import hashlib
import json

from infrastructure.shared.agent.files import editable_application_path
from infrastructure.shared.agent.feedback import CheckFailure
from infrastructure.shared.agent.incremental import RequirementCheckpoints
from infrastructure.shared.agent.recovery import implementation_task
from infrastructure.shared.agent.testing_reference import testing_reference
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
from infrastructure.stages.frontend.triggers.e2e_runtime import CONFIG, FIXTURE, VITE_CONFIG, prepare_e2e
from infrastructure.stages.frontend.verification import verify_frontend, require_stable_acceptance
from infrastructure.stages.frontend.triggers.testing import E2EChecks, test_path
from infrastructure.stages.frontend.ui.runtime import APPLICATION_ENTRYPOINTS, prepare_frontend
from infrastructure.stages.requirements.acceptance import source_expectations, test_accounts, require_scenario_coverage
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
    oracles = {rid:source_expectations(raw,rid) for rid in order}
    save_json(arc_dir/'acceptance_evidence.json',oracles)
    console = DemoConsole(pause)
    runtime = {}
    def bind_checks():
        runtime['checks'] = E2EChecks(output)
    preparation = prepare_with_recovery(arc_dir,[
        ('node_runtime',bind_checks),
        ('frontend_runtime',lambda:prepare_frontend(output)),
        ('browser_runtime',lambda:prepare_e2e(output,backend)),
        ('dependencies',lambda:install_dependencies(output)),
        ('arco_types',lambda:validate_component_types(output)),
        ('chromium',lambda:runtime['checks'].install_browser())],console,report_name='frontend_preparation.json')
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
    plan.update(architecture='native_leaf_design_tests_tdd',status='IMPLEMENTING')
    report = {'status':'IMPLEMENTING','architecture':'native_leaf_design_tests_tdd','order':order,
        'requirements':{},'tests':{},'preparation':preparation}
    # Existing source, UI evidence and actual endpoint changes all invalidate stale
    # acceptance. Source import associations protect unrelated accepted pages.
    resume = RequirementCheckpoints(arc_dir,'frontend',raw,lambda rid:{
        'version':'native_frontend_v2_navigation_accessibility','schema':schema,
        'backend':backend,'source_context':contexts[rid],'design':selected_design(plan,rid)})
    references = arco_references()
    if (output/'reference').is_dir():
        references['references/source'] = output/'reference'
    accepted, last_agent = [], None
    dependency_paths = ('frontend/package.json','package-lock.json','npm-shrinkwrap.json','frontend/package-lock.json')
    fixture_paths = [FIXTURE,CONFIG,VITE_CONFIG,'frontend/tests/e2e/support/helpers.ts',
        'frontend/tests/e2e/support/navigation.ts','frontend/src/components/accessibility.tsx','backend/tests/support/helpers.ts']
    for rid in order:
        relative = test_path(rid)
        reused = resume.reuse(rid)
        if reused:
            report['requirements'][rid] = reused
            accepted.append(rid)
            report['tests'][rid] = relative
            console.show('Frontend | Reuse '+rid,'Accepted source, tests, evidence and design are unchanged; cumulative regression remains enabled.')
            continue
        entry = report['requirements'][rid] = {'status':'DESIGNING','requirements':[rid],'test_path':relative}
        save_json(arc_dir/'frontend_e2e.json',report)
        agent = None
        with implementation_task(output,entry,console,'Frontend design/tests/implementation '+rid,extra_paths=dependency_paths):
            holder = {}
            def writable(path, _holder=holder, _test=relative):
                owner = _holder['agent']
                if path==_test:
                    return not owner.require_build and (owner.phase=='tests' or owner.allow_test_repair)
                return owner.phase=='implementation' and path.startswith('frontend/src/') and editable_application_path(output,path)
            files = FileTools(output,['frontend','backend'],requirements=[rid],stage='frontend',
                discovery=True,references=references,files=[*APPLICATION_ENTRYPOINTS,PROVIDER_PATH,FIXTURE,relative],allow_write=writable)
            current = [test_path(key) for key in [*accepted,rid]]
            expectations = [oracles[key] for key in [*accepted,rid]]
            def ensure_dependencies(owner):
                if owner.pending_dependencies:
                    install_dependencies(output)
                    owner.pending_dependencies = False
            def compile_tests(owner, _relative=relative):
                ensure_dependencies(owner)
                result = cached.typecheck([_relative],full_source=False)
                if result['returncode']:
                    raise CheckFailure('Current browser test compilation failed',result)
                return {'typecheck':result}
            def acceptance(owner, _current=tuple(current), _expected=tuple(expectations)):
                ensure_dependencies(owner)
                selected = [test_path(key) for key in accepted] if owner.require_build else list(_current)
                expected = [oracles[key] for key in accepted] if owner.require_build else list(_expected)
                result = {'typecheck':cached.typecheck(selected)}
                if result['typecheck']['returncode']:
                    raise CheckFailure('Frontend source/test compilation failed',result)
                result['e2e'] = cached.tests(selected)
                try:
                    require_stable_acceptance(result['e2e'])
                    for oracle in expected:
                        require_scenario_coverage(result['e2e'],oracle)
                except ValueError as error:
                    raise CheckFailure('Real-browser source acceptance or cumulative regression failed',result) from error
                if owner.require_build:
                    result['build'] = cached.build()
                    if result['build']['returncode']:
                        raise CheckFailure('Final application build failed',result)
                return result
            draft_path = arc_dir/'frontend_node_drafts'/(hashlib.sha256(rid.encode()).hexdigest()[:20]+'.json')
            def publish_phase(phase, _entry=entry):
                _entry['status'] = {'tests':'GENERATING_TESTS','implementation':'IMPLEMENTING'}.get(phase,'DESIGNING')
                save_json(arc_dir/'frontend_e2e.json',report)
            agent = FrontendBuildAgent(plan,backend,schema,rid,files,acceptance,compile_tests,
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
            task = {'requirement':contexts[rid],'source_expectations':oracles[rid],
                'ancestor_rules':list(reversed(ancestors)),
                'ui_candidates':{key:plan['items'][key] for key in sorted(related) if key in plan['items']},
                'backend_inventory':{key:{field:api[field] for field in ('description','signature','implementation') if field in api}
                    for key,api in backend['apis'].items()},
                'related_api_ids':backend.get('requirements',{}).get(rid,[]),
                'provided_schema':requirement_schema(schema,rid),
                'schema_inventory':{name:list(entity['fields']) for name,entity in schema['entities'].items()},
                'frontend_stack':stack_context(),'component_knowledge':components,
                'test_accounts':test_accounts(raw),'test_path':relative,'test_support':FIXTURE,
                'application_entrypoints':list(APPLICATION_ENTRYPOINTS),
                'previous_failure':{key:previous.get('requirements',{}).get(rid,{}).get(key) for key in ('error','feedback','archive')}}
            task['test_mechanics_reference'] = testing_reference(task)
            task['test_mechanics_reference']['source_driven_transport'] = ('Use actual backend contracts. Fixed loginGiven/browserIdentity/ownGiven '
                'examples are usable only if their HTTP/schema assumptions match this source; otherwise use real source transport and explicit Given records.')
            task['accessibility_reference'] = {'path':'frontend/src/components/accessibility.tsx',
                'usage':'Import selectAriaLabel/requiredLabel from the shared helper. Spread selectAriaLabel(originalLabel) '
                    'on Arco Select; do not add a second input/label association. Preserve this helper across features.'}
            task['navigation_reference'] = {'path':'frontend/tests/e2e/support/navigation.ts',
                'exports_from_test_support':['navigateAndAssert','chooseNamedOption','NavigationCheck'],
                'usage':'await navigateAndAssert(page,{trigger: realMenuOrLink, targetURL: actualURLPattern, landmark: '
                    'pageSpecificLocator, reload: true, history: {sourceURL: actualPreviousURL, sourceLandmark: previousPageLocator}}); '
                    'Omit history/reload only when not applicable to source behavior. chooseNamedOption(page,sourceLabel,sourceOption) '
                    'checks one combobox before clicking. No business paths or fixture data are assumed.',
                'accepted_route_hints':[{key:item[key] for key in ('purpose','route','implementation_hint') if key in item}
                    for item in plan['items'].values() if isinstance(item.get('route'),str) and item['route'].startswith('/')]}
            task['landing_files'] = {}
            for path in [*APPLICATION_ENTRYPOINTS,PROVIDER_PATH,FIXTURE,relative,'frontend/src/components/accessibility.tsx']:
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
                entry.update(verification_scope='real_browser_with_cumulative_regression',passed=entry['checks']['e2e'].get('passed',0))
        if entry['status'] in {'GREEN','NO_UI'}:
            plan = agent.plan
            publish_plan(arc_dir,plan)
            if entry['status']=='GREEN':
                accepted.append(rid)
                report['tests'][rid] = relative
                last_agent = agent
                resume.refresh_accepted(report['requirements'],lambda key:[test_path(key),*fixture_paths,
                    *[item['implementation_hint'] for item in selected_design(plan,key).values()
                        if item.get('implementation_hint') and (output/item['implementation_hint']).is_file()]])
        save_json(arc_dir/'frontend_e2e.json',report)
    built = cached.build()
    if built['returncode'] and last_agent is not None:
        last_agent.plan = deepcopy(plan)
        repair = report['integration_repair'] = {'status':'IMPLEMENTING','requirements':[last_agent.rid]}
        with implementation_task(output,repair,console,'Frontend integration repair in retained context',extra_paths=dependency_paths):
            last_agent.repair_integration(built,console)
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
    return verify_frontend(arc_dir,tree,backend,ui,console,report,checks=cached)
