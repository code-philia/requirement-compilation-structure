"""Real-app browser checks and executable E2E RED/GREEN gates."""

from hashlib import sha256
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from infrastructure.stages.frontend.triggers.e2e_runtime import RUNNER
from infrastructure.stages.frontend.ui.testing import FrontendChecks, parse_playwright_result, require_green, require_red
from infrastructure.shared.project.entrypoints import selected_path


def test_path(rid, output=None):
    """Return a safe, stable E2E spec path for one requirement."""
    chosen = selected_path(output, "e2e_test", rid) if output is not None else None
    if chosen:
        return chosen
    slug = rid if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", rid) else "requirement-" + sha256(rid.encode()).hexdigest()[:12]
    return f"frontend/tests/e2e/{slug}.spec.ts"


def require_behavioral_red(result):
    """Require observable behavioral assertion failures and reject server, browser, or runtime failures."""
    try:
        require_red(result)
    except ValueError as error:
        raise ValueError(f"Expected behavioral assertion RED, not server/browser/runtime failure: {result}") from error


class E2EChecks(FrontendChecks):
    """Real-app Playwright checks with isolated test data."""
    def __init__(self, output, maximum=2):
        """Reuse the ten-minute frontend command timeout and a per-requirement test-count hint."""
        super().__init__(output)
        self.maximum = maximum

    def typecheck(self, files, full_source=True):
        """Compile UI and E2E tests, optionally restricting application sources during test generation."""
        return super().typecheck(files, test_roots=("frontend/tests/ui", "frontend/tests/e2e"),
            source_files=("src/**/*.ts", "src/**/*.tsx") if full_source else ("src/main.tsx",))

    def tests(self, files):
        """Run only selected E2E specs with an owned temporary database, clean it up, ."""
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
        return result
