"""Independent requirement acceptance, separate from implementation-owned tests."""

from hashlib import sha256
import yaml

from infrastructure.shared.agent.files import FileWorkspace
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.discovery import ContextIndex
from infrastructure.shared.agent.conventions import task_conventions
from infrastructure.stages.backend.context import requirement_context, related_schema
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.frontend.triggers.implementation import scenario_context
from infrastructure.stages.frontend.triggers.e2e_runtime import FIXTURE
from infrastructure.stages.frontend.triggers.testing import E2EChecks
from infrastructure.stages.frontend.ui.testing import require_green
from infrastructure.utils.files import save_json
from infrastructure.shared.project.git import checkpoint

INSTRUCTIONS = '''Write independent final acceptance tests for ONE original requirement.
Derive expected results from original_requirement and its Given/When/Then scenarios.
Interface details are supplied only to locate UI elements/routes and prepare valid Given
fixtures; they are not authority to weaken an original business requirement. Neither
application source nor implementation-owned tests are supplied. Do not infer expected
behavior from an observed implementation result or duplicate process smoke tests.

Write a small Playwright suite at test_path using the supplied test/expect/database
fixture. Drive When actions through the real browser without mocks or injected state.
Use UI IDs or accessible locators for actions. Assert original required visible business
outcomes, not design-inferred internal labels or every DOM attribute. Cover main success,
critical rejection, correct identity/ownership, and refresh/persistence WHEN required.
Use two distinct identities where identity isolation matters; a test that only creates
one account cannot reject an implementation returning the first account for everyone.
For required rejection-without-writes, verify the relevant persisted result is unchanged.
Prefer user-visible outcomes over unspecified cookie/hash encodings or storage strategies.
There is no arbitrary test-count quota: cover the few important outcomes for this task.

Seed minimal valid Given records using the documented database/test utilities. Application
sources, shared fixtures, original requirements and other suites are not editable.
During generation only TypeScript is checked; missing application behavior is a useful
acceptance failure, never a reason to weaken assertions. Return ordinary file edits.'''

REVIEW_INSTRUCTIONS = '''Review this independent acceptance test against the original requirement.
This is a separate test review, not implementation repair. Actual failure evidence is
provided. Diagnose test_requirement_mismatch, test_overconstraint, environment, or
implementation. Change ONLY test_path if specific original requirement or fixture evidence
shows the test is wrong. Preserve every required business outcome. If the implementation
or environment is wrong, return edits=[] and explain it; the failed acceptance remains
failed. Compilation passing is enough to finish this review; you are NOT asked to turn a
business failure GREEN. Never adjust expected values just to match observed wrong behavior.
Use original requirements as authority; no application source or process tests are available.'''


def require_acceptance(result):
    require_green(result)
    if result.get('skipped') or result.get('flaky'):
        raise ValueError('Independent acceptance includes skipped or unstable tests')


def acceptance_path(rid):
    return 'frontend/tests/e2e/acceptance/' + sha256(rid.encode()).hexdigest()[:12] + '.spec.ts'


def original_requirements(input_dir):
    """Read the original YAML again; no generated design is used as the test oracle."""
    path = input_dir / 'requirements.yaml'
    if not path.is_file():
        raise ValueError('Independent acceptance requires original input/requirements.yaml')
    return RequirementTree(yaml.safe_load(path.read_text(encoding='utf-8-sig')))


def run_independent_acceptance(input_dir, arc_dir, schema, backend, ui, design, model, console, max_turns=10):
    output = arc_dir.parent.resolve()
    tree = original_requirements(input_dir)
    checks = E2EChecks(output)
    report = {'status': 'RUNNING', 'requirements': {}}
    save_json(arc_dir / 'independent_acceptance.json', report)
    for rid in tree.leaves:
        path = acceptance_path(rid)
        entry = {'status': 'GENERATING', 'test_path': path}
        report['requirements'][rid] = entry
        label = 'Independent acceptance / ' + rid
        try:
            context = scenario_context(ui, design, rid)
            aids = backend['requirements'].get(rid, [])
            apis = {aid: backend['apis'][aid] for aid in aids}
            task = {'original_requirement': requirement_context(tree, rid), 'test_path': path,
                'ui_interfaces': {pid: {key: page[key] for key in ('route', 'root', 'elements')}
                    for pid, page in context['page_subtrees'].items()},
                'api_interfaces': {aid: {key: value for key, value in api.items()
                    if key in ('signature', 'request', 'response')} for aid, api in apis.items()},
                'schema': related_schema(schema, apis.values())}
            if not task['ui_interfaces']:
                entry.update(status='FAILED', error='No UI interface available for independent requirement acceptance; not verified')
                continue
            task['shared_conventions'] = task_conventions(output, {'requirement': task['original_requirement']})
            # This restricted index cannot reveal implementation or process-test source.
            index = ContextIndex({'requirement': {rid: task['original_requirement']},
                'schema': task['schema'], 'api': task['api_interfaces']})
            workspace = FileWorkspace(output, [path], references=[FIXTURE, 'backend/tests/support/context.ts'])

            def compile_suite():
                if not (output / path).is_file():
                    raise ValueError('Create the supplied acceptance test_path')
                result = checks.typecheck([path], full_source=False)
                if result['returncode']:
                    raise ValueError(result['output'])
                return result

            if not (output / path).is_file():
                agent = run_file_agent(model, INSTRUCTIONS, task, workspace, compile_suite,
                    max_turns, console, label + ' / Generation', context_index=index)
                entry['generation_turns'] = agent['turns']
            result = checks.tests([path])
            entry["result"] = result
            try:
                require_acceptance(result)
            except ValueError:
                # A separate, requirement-grounded review may correct the test, but its
                # gate intentionally does not demand behavioral GREEN.
                entry['initial_failure'] = result
                save_json(arc_dir / 'independent_acceptance.json', report)
                checkpoint(output, stage="12", task=rid, action="Record independent acceptance before test review",
                    status="FAILED", details={"test_path": path, "checks": result})
                review = run_file_agent(model, REVIEW_INSTRUCTIONS, task, workspace, compile_suite,
                    max_turns, console, label + ' / Test review', feedback=result, context_index=index)
                entry['review_turns'] = review['turns']
                result = checks.tests([path])
                entry["result"] = result
                require_acceptance(result)
            entry.update(status='GREEN', result=result)
        except (ValueError, RuntimeError) as error:
            entry.update(status='FAILED', error=str(error))
        finally:
            save_json(arc_dir / 'independent_acceptance.json', report)
            checkpoint(output, stage="12", task=rid, action="Publish independent requirement acceptance",
                status=entry['status'], details=entry)
            console.show(label + ' | ' + entry['status'], entry.get('error', 'Real acceptance checks completed'))
    report['status'] = 'GREEN' if report['requirements'] and all(
        entry['status'] == 'GREEN' for entry in report['requirements'].values()) else 'COMPLETED_WITH_FAILURES'
    save_json(arc_dir / 'independent_acceptance.json', report)
    checkpoint(output, stage="12", task="independent acceptance", action="Publish final independent acceptance report",
        status=report['status'], details=report)
    return report
