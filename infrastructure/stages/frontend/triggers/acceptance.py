"""Original requirement evidence and test policies for single-pass frontend TDD."""

import yaml

from infrastructure.stages.requirements.tree import RequirementTree

INSTRUCTIONS = '''Write requirement acceptance tests for ONE original requirement after its initial implementation.
source_expectations is a model-free copy of original scenarios and external data, not
generated API/UI expectations. Cover EVERY supplied source scenario and include its
SCN ID verbatim in an executed test title. Assert actual Then outcomes, forbidden writes,
isolation and lifecycle values; a matching title alone is not a business assertion.
test_accounts supplies explicit SEED fixture credentials for real browser login. Do not
copy credentials into production UI or invent a registration workflow. CREATED data
must be created through the scenario operation; DERIVED data must follow real processing.
Derive expected results from requirement and its Given/When/Then scenarios.
Read project files as needed to understand test configuration, database initialization,
fixtures, UI locators and API wiring. Source code and existing tests describe how to run
the application; they are not authority for expected business behavior. Derive assertions
from the original requirement, not the current implementation or process smoke tests.
Only test_path is writable. Reading a file does not grant permission to modify it.

Write a small Playwright suite at test_path using the supplied test/expect/database
fixture. Drive When actions through the real browser without mocks or injected state.
Import test and expect from frontend/tests/e2e/support/context.ts with a relative .js import.
For required export/download interactions, click the actual control and observe the
browser download and its contents; a direct API call plus button visibility does not
prove the frontend interaction. Direct unauthorized requests supplement hidden-control
checks when server enforcement is required.
Use UI IDs or accessible locators for actions. Preserve explicitly required names, labels
and roles; do not learn different business expectations from current application code.
Use concrete routes and object identities; :id and {id} are route patterns, not literal URLs.
Assert original required visible business
outcomes, not design-inferred internal labels or every DOM attribute. Cover main success,
critical rejection, correct identity/ownership, and refresh/persistence WHEN required.
Use two distinct identities where identity isolation matters; a test that only creates
one account cannot reject an implementation returning the first account for everyone.
For required rejection-without-writes, verify the relevant persisted result is unchanged.
Prefer user-visible outcomes over unspecified cookie/hash encodings or storage strategies.
For a When action requiring one API operation, also observe its relevant method/endpoint and
reject duplicate submissions when the requirement expects one operation. Start observing
before the action, wait for its response and business completion, and exclude unrelated
page-entry calls or explicitly required retries. Do not count all requests globally.
For rapid repeated activation, do not start concurrent locator.click calls on a control
that the first successful action may disable or remove: independent auto-wait loops can
race and time out after a correct single submission. Use locator.dblclick() so Playwright
scrolls to the control, checks actionability once and dispatches a real double-click.
If raw mouse coordinates are necessary, scroll the control into view before measuring
its position; DOM visibility alone does not imply that it is inside the viewport. Observe requests and persisted outcomes to verify exactly-once effects; do not
require a submitting button to remain enabled or visible after successful navigation.
There is no arbitrary test-count quota: cover the few important outcomes for this task.

The database fixture restores requirement-defined startup data before each test. Reuse
those records when required; do not assume an empty database or insert duplicate identities.
Use prerequisite records to isolate the current requirement from other requirements'
registration/creation implementations. Arrange scenario-specific absence or conflicting
Given states in the isolated test database; still drive the current When through the UI.
Seed additional minimal valid Given records using the documented database/test utilities. Application
sources, shared fixtures, original requirements and other suites are not editable.
Generation checks test compilation only. The subsequent acceptance gate runs the real browser. Missing application
behavior is useful RED for implementation, never a reason to weaken assertions. Use edit_file to create or repair only test_path under frontend/tests/e2e/.'''

REVIEW_INSTRUCTIONS = '''Review this requirement acceptance test against the original requirement.
This is a separate test review, not implementation repair. Actual failure evidence is
provided. Diagnose test_requirement_mismatch, test_overconstraint, environment, or
implementation. Change ONLY test_path if specific original requirement or fixture evidence
shows the test is wrong. Preserve every required business outcome. If the implementation
or environment is wrong, return tool_calls=[] and explain it; the failed acceptance remains
failed. Compilation passing is enough to finish this review; you are NOT asked to turn a
business failure GREEN. Never adjust expected values just to match observed wrong behavior.
Read project files as needed to understand wiring, fixtures and failure evidence. Use
original requirements as authority for expected business behavior; source code and existing
tests do not override them. Only test_path is writable; all other files remain read-only.'''


def original_requirements(input_dir):
    """Use the original YAML as the behavioral authority for implementation and tests."""
    path = input_dir / 'requirements.yaml'
    if not path.is_file():
        raise ValueError('Requirement acceptance requires original input/requirements.yaml')
    return RequirementTree(yaml.safe_load(path.read_text(encoding='utf-8-sig')))


# Shared prompt advice avoids recurring fixture/Playwright type mismatches.
INSTRUCTIONS += """
Use Playwright APIResponse for page.request/fetch API responses and Response for page
network events/waitForResponse. They are different types. A helper accepting both page
and dialog scope should type its argument Page | Locator, not Locator only. Use the
actual accessible names rendered by the implemented UI while retaining source labels.
Do not infer expected business results from that UI. Do not launch tests from tools;
the host handles the subsequent real-browser acceptance.
"""


INSTRUCTIONS += """
Import prepareGiven from the same fixture module. Wrap ONLY isolated Given setup and
its prerequisite checks in await prepareGiven(async () => { ... }); return needed rows.
Create minimal prerequisite warehouse/product/etc. rows there when source scenarios
require them. Earlier tests do not leave rows behind. Do not wrap UI When actions,
Then assertions, real feature failures or network/environment errors to relabel them
as setup failures. Never fix missing Given state by adding production startup seed.
"""
