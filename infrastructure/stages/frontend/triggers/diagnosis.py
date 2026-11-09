"""Narrow, source-cited escalation from implementation repair to isolated test repair."""

import json

from infrastructure.shared.agent.feedback import compact_feedback
from infrastructure.stages.requirements.acceptance import require_scenario_coverage


def fixture_failure(result):
    return 'ARC_FIXTURE_SETUP:' in json.dumps(result, ensure_ascii=False)


def diagnose(model, source, feedback):
    """One diagnosis only after a stalled loop; no automatic assertion relaxation."""
    response = model.generate_json('''Diagnose a repeated failure using original source and actual feedback.
Return {"cause":"test_setup|test_mismatch|implementation|environment|source_conflict",
"source_refs":["exact source scenario ID"],"reason":"concrete evidence",
"repair":"minimal change"}. Test setup means isolated Given rows/preconditions are
missing; those never belong in production seed. A test mismatch requires a specific
original source rule contradicting an assertion. Do not infer incorrect tests merely
because code fails. If uncertain choose implementation. Do not return code.''',
        {'source_expectations': source, 'actual_feedback': compact_feedback(feedback)})
    known = {row['id'] for row in source['scenarios']} | {source['requirement']}
    if not isinstance(response, dict):
        return {'cause': 'implementation', 'reason': 'Diagnosis did not return evidence'}
    if response.get('cause') in {'test_setup', 'test_mismatch'} and (
            not response.get('reason') or not response.get('repair') or not response.get('source_refs')
            or not set(response['source_refs']) <= known):
        return {'cause': 'implementation', 'reason': 'No valid original-source evidence for editing tests'}
    return response


def source_coverage(tree, raw, report, output, path_for, executed=None):
    from infrastructure.stages.requirements.acceptance import source_expectations
    excluded, missing_suites, missing_scenarios = [], [], []
    for rid in tree.leaves:
        entry = report['requirements'].get(rid, {})
        if entry.get('status') == 'NO_UI':
            excluded.append({'requirement': rid, 'reason': entry.get('error', 'No direct UI')})
            continue
        source = source_expectations(raw, rid)
        if not (output / path_for(rid)).is_file():
            missing_suites.append(rid)
            missing_scenarios.extend(row['id'] for row in source['scenarios'])
        elif executed is not None:
            for row in source['scenarios']:
                try:
                    require_scenario_coverage(executed, {'scenarios': [row]})
                except ValueError:
                    missing_scenarios.append(row['id'])
    return {'status': 'FAILED' if missing_suites or missing_scenarios else 'GREEN',
        'missing_requirements': missing_suites, 'missing_scenarios': missing_scenarios,
        'excluded_no_ui': excluded}
