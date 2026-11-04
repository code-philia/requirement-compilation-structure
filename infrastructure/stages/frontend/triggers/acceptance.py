"""Original requirement evidence and test policies for single-pass frontend TDD."""

import yaml

from infrastructure.stages.requirements.tree import RequirementTree

INSTRUCTIONS = '''Write requirement acceptance tests for ONE original requirement before its implementation.
Derive expected results from requirement and its Given/When/Then scenarios.
Read project files as needed to understand test configuration, database initialization,
fixtures, UI locators and API wiring. Source code and existing tests describe how to run
the application; they are not authority for expected business behavior. Derive assertions
from the original requirement, not the current implementation or process smoke tests.
Only test_path is writable. Reading a file does not grant permission to modify it.

Write a small Playwright suite at test_path using the supplied test/expect/database
fixture. Drive When actions through the real browser without mocks or injected state.
Import test and expect from frontend/tests/e2e/support/context.ts with a relative .js import.
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
There is no arbitrary test-count quota: cover the few important outcomes for this task.

The database fixture restores requirement-defined startup data before each test. Reuse
those records when required; do not assume an empty database or insert duplicate identities.
Use prerequisite records to isolate the current requirement from other requirements'
registration/creation implementations. Arrange scenario-specific absence or conflicting
Given states in the isolated test database; still drive the current When through the UI.
Seed additional minimal valid Given records using the documented database/test utilities. Application
sources, shared fixtures, original requirements and other suites are not editable.
Compilation and a real browser run check the suite during generation. Missing application
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
