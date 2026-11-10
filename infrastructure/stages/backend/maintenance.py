"""Route test mechanics failures to bounded, source-cited test-only maintenance."""

import json

from infrastructure.shared.agent.feedback import TestSetupRequired, compact_feedback
from infrastructure.stages.frontend.triggers.diagnosis import diagnose

RULES = '''Repair only the supplied test files for the evidenced test setup/mechanics mismatch.
Original requirements and source_expectations are immutable authority. Preserve all
original scenario IDs, When API operations, expected statuses/results, rejection,
isolation and persistence assertions. Do not make tests match broken business code.
Use fixed findGiven/ensureGiven/sessionIdentity/readResponse for actual schema/identity
mechanics. No business values, memberships or fixture rows may be invented. Never
modify production code/seeds, skip assertions, catch business failures as success, or
move When/Then inside prepareGiven. Stop after setup/mechanics are corrected even if
business assertions are still RED; those return to implementation repair.
'''


def mechanics_failure(report):
    text = json.dumps(report, ensure_ascii=False)
    if 'ARC_FIXTURE_SETUP:' in text:
        return 'test_setup'
    if any(marker in text for marker in ('Body is unusable', 'Body has already been read', 'body used already')):
        return 'test_mechanics'
    return None


def diagnose_failure(model, expectations, feedback):
    # No automatic weakening of SQL/permission/status assertions. Uniqueness and FK
    # errors alone are NOT proof of a test defect: they can be real When behavior.
    cause = mechanics_failure(feedback)
    if cause:
        return {'cause': cause, 'source_refs': [item['requirement'] for item in expectations],
            'reason': 'Explicit isolated Given marker or consumed Response body in executed test evidence',
            'repair': 'Correct isolated setup/body consumption only; preserve source When/Then'}
    merged = {'requirement': expectations[0]['requirement'],
        'scenarios': [row for item in expectations for row in item['scenarios']],
        'source_requirements': expectations}
    try:
        return diagnose(model, merged, feedback)
    except (ValueError, RuntimeError):
        return {'cause': 'implementation', 'reason': 'No reliable source-cited test diagnosis'}


def reject_mechanics(report):
    if mechanics_failure(report):
        raise TestSetupRequired('HTTP test setup/mechanics need narrow maintenance', compact_feedback(report))
