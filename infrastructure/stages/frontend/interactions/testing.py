"""Scenario traceability, real-app browser checks, and E2E RED/GREEN gates."""

from hashlib import sha256
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from infrastructure.stages.frontend.interactions.e2e_runtime import RUNNER
from infrastructure.stages.frontend.ui.testing import FrontendChecks, parse_playwright_result, require_green, require_red


def test_path(rid):
    """Return a safe, stable E2E spec path for one requirement."""
    slug = rid if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", rid) else "requirement-" + sha256(rid.encode()).hexdigest()[:12]
    return f"frontend/tests/e2e/{slug}.spec.ts"


def validate_test_source(source, step_ids, event_ids, maximum):
    """Require a small browser-driven suite tracing all selected steps/events; reject skips, API mocks, and direct API calls."""
    titles = re.findall(r"\btest\(\s*(['\"])(.*?)\1\s*,", source, re.DOTALL)
    if not titles or len(titles) > maximum or not re.search(r"from\s+['\"]\./support/context(?:\.js)?['\"]", source):
        raise ValueError(f"Use 1..{maximum} literal test(...) cases importing test/expect from ./support/context.js")
    if re.search(r"\b(?:test|describe)\.(?:skip|fixme|only|fail)\b|\bmock\b|\.route\s*\(|\.fulfill\s*\(|\.request\b|\bfetch\s*\(|addInitScript|__ARC_UI_FIXTURE__|process\.exit|node:(?:fs|child_process)|require\s*\(", source):
        raise ValueError("E2E cases may not skip, mock APIs, call APIs directly, inject UI fixtures, or modify infrastructure")
    if not re.search(r"await\s+expect(?:\.|\()", source) or not re.search(r"page\.(?:goto|getBy|locator)", source):
        raise ValueError("Drive the real page and await observable Playwright assertions")
    names = "\n".join(title for _, title in titles)
    tokens = {f"STEP:{sid}" for sid in step_ids} | {f"EVENT:{eid}" for eid in event_ids}
    missing = [token for token in sorted(tokens) if not re.search(r"(?<![A-Za-z0-9_.:-])" + re.escape(token) + r"(?![A-Za-z0-9_.:-])", names)]
    if missing:
        raise ValueError(f"Trace every required scenario step and newly implemented event in test titles: {missing}")
    return len(titles)


def require_behavioral_red(result):
    """Require observable behavioral assertion failures and reject server, browser, or runtime failures."""
    try:
        require_red(result)
    except ValueError as error:
        raise ValueError(f"Expected behavioral assertion RED, not server/browser/runtime failure: {result}") from error


class E2EChecks(FrontendChecks):
    """Real-app Playwright checks with isolated test data and per-spec case-count enforcement."""
    def __init__(self, output, maximum=5):
        """Reuse frontend checks with a longer real-server timeout and an enforced per-requirement test budget."""
        super().__init__(output, timeout=300)
        self.maximum = maximum

    def typecheck(self, files, full_source=True):
        """Compile UI and E2E tests, optionally restricting application sources during test generation."""
        return super().typecheck(files, test_roots=("frontend/tests/ui", "frontend/tests/e2e"),
            source_files=("src/**/*.ts", "src/**/*.tsx") if full_source else ("src/main.tsx",))

    def tests(self, files):
        """Run only selected E2E specs with an owned temporary database, clean it up, and verify executed case counts."""
        if not files:
            raise ValueError("Do not run empty E2E suites")
        for relative in files:
            if not (self.output / relative).resolve().is_relative_to(self.output / "frontend/tests/e2e"):
                raise ValueError("Run only the selected E2E test suites")
        # The Node runner creates a child directory here. Python also removes
        # it after timeout/interruption, so test databases never persist.
        with TemporaryDirectory(prefix="arc-e2e-owner-") as temporary:
            env = {**os.environ, "ARC_E2E_TEMP_ROOT": temporary}
            print("Playwright E2E | real backend + isolated database | " + ", ".join(files), flush=True)
            result = self.execute([RUNNER, *files], env=env)
        result = parse_playwright_result(result, include_files=True)
        counts = {Path(path).name: count for path, count in result["files"].items()}
        for relative in files:
            count = counts.get(Path(relative).name, 0)
            if not 1 <= count <= self.maximum:
                raise ValueError(f"Keep 1..{self.maximum} executed tests in {relative}; found {count}")
        return result
