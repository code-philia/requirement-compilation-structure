"""Real-app browser checks with executable acceptance and repair evidence."""

from hashlib import sha256
import os
import re
from tempfile import TemporaryDirectory

from infrastructure.stages.frontend.triggers.e2e_runtime import RUNNER
from infrastructure.stages.frontend.ui.testing import FrontendChecks, parse_playwright_result


def test_path(rid):
    """Return a safe, stable E2E spec path for one requirement."""
    slug = rid if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", rid) else "requirement-" + sha256(rid.encode()).hexdigest()[:12]
    return f"frontend/tests/e2e/{slug}.spec.ts"


class E2EChecks(FrontendChecks):
    """Real-app Playwright checks with isolated test data."""
    def typecheck(self, files, full_source=True):
        """Compile UI and E2E tests, optionally restricting application sources during test generation."""
        return super().typecheck(files, test_roots=("frontend/tests/ui", "frontend/tests/e2e"),
            source_files=("src/**/*.ts", "src/**/*.tsx") if full_source else ())

    def tests(self, files):
        """Run selected E2E specs and keep startup/runner failures available for repair."""
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
            try:
                result = self.execute([RUNNER, *files], env=env)
            except (ValueError, RuntimeError, OSError) as error:
                return {"returncode": 1, "output": str(error), "errors": [str(error)],
                    "passed": 0, "failed": 0, "files": {}}
        try:
            return parse_playwright_result(result, include_files=True)
        except ValueError as error:
            # A runner/startup failure may not produce reporter JSON. Keep its logs
            # as repair evidence instead of rejecting the generated business test.
            return {**result, "returncode": result["returncode"] or 1,
                "errors": [str(error)], "passed": 0, "failed": 0, "files": {}}
