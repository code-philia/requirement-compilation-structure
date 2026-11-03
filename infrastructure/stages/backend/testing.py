"""Execute actual backend compilation and tests without source/title policy gates."""

from infrastructure.shared.agent.feedback import CheckFailure

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from infrastructure.utils.processes import capture_process, npm_command


class BackendChecks:
    """Compiler-owned TypeScript and Node test commands; generated code cannot choose shell commands."""
    def __init__(self, output: Path, timeout: int = 600) -> None:
        """Bind fixed backend check commands to the generated workspace and require an available Node.js executable."""
        self.output = output.resolve()
        self.timeout = timeout
        self.node = shutil.which("node")
        if self.node:
            self.node = str(Path(self.node).resolve())
        if not self.node or not (self.output / "node_modules/typescript/bin/tsc").is_file() or not (self.output / "node_modules/tsx").is_dir():
            raise ValueError("Node.js and workspace dev dependencies (typescript/tsx) are required for backend checks")

    def execute(self, argv: list[str], executable: str | None = None) -> dict:
        """Run a fixed Node command in the workspace and return its exit code and captured output."""
        try:
            result = capture_process([executable or self.node, *argv], cwd=self.output, timeout=self.timeout)
        except subprocess.TimeoutExpired as error:
            raise ValueError(f"Backend check timed out after {self.timeout}s") from error
        return {"returncode": result["returncode"], "output": result["output"]}

    def build(self) -> dict:
        """Build the backend, including publication of its SQL runtime assets."""
        command = npm_command()
        return self.execute([*command[1:], "run", "build", "--workspace", "@arc/backend"], executable=command[0])

    def typecheck(self, files: list[str] | None = None) -> dict:
        """Compile selected backend tests with TypeScript, using and cleaning a temporary test configuration."""
        if files is None:
            return self.execute(["node_modules/typescript/bin/tsc", "--noEmit", "-p", "backend/tsconfig.test.json"])
        # Compile the complete real-server source tree and only the selected suites.
        includes = ["src/**/*.ts"]
        for relative in dict.fromkeys(files):
            path = (self.output / relative).resolve()
            if not path.is_relative_to(self.output / "backend/tests"):
                raise ValueError(f"Test path is outside backend/tests: {relative}")
            includes.append(path.relative_to(self.output / "backend").as_posix())
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", suffix=".json", prefix=".tsconfig-tdd-", dir=self.output / "backend", delete=False) as config:
            temporary = Path(config.name)
            json.dump({"extends": "./tsconfig.test.json", "compilerOptions": {"forceConsistentCasingInFileNames": True}, "files": [], "include": includes}, config)
        try:
            return self.execute(["node_modules/typescript/bin/tsc", "--noEmit", "-p", str(temporary)])
        finally:
            temporary.unlink(missing_ok=True)

    def tests(self, files: list[str]) -> dict:
        """Start the real backend through the owned HTTP runner and parse test TAP counts."""
        if not files:
            return {"returncode": 0, "output": "No tests for this empty API set.", "tests": 0, "pass": 0, "fail": 0}
        try:
            captured = capture_process([self.node, "backend/scripts/test-api.mjs", *files],
                cwd=self.output, timeout=self.timeout)
        except subprocess.TimeoutExpired as error:
            raise ValueError(f"Backend HTTP checks timed out after {self.timeout}s") from error
        result = {"returncode": captured["returncode"], "output": captured["output"]}
        # Parse complete test stdout so backend stderr cannot hide TAP results.
        tap = captured["stdout"]
        for kind in ("tests", "pass", "fail", "skipped", "todo"):
            found = re.search(rf"^# {kind} (\d+)\s*$", tap, re.MULTILINE)
            result[kind] = int(found.group(1)) if found else 0
        # TAP diagnostic blocks contain the assertion, stack and source location.
        # Successful subtests remain in the saved tool report, not repair context.
        failures = re.findall(r"(?m)^\s*not ok[^\n]*\n(?:[ \t]+[^\n]*\n)*", tap)
        if failures:
            result["failures"] = failures
        return result


def require_green(report: dict) -> None:
    """Reject a test report unless the selected suite passed."""
    if report["returncode"] != 0 or not report.get("pass") or report.get("fail") or report.get("skipped") or report.get("todo"):
        raise CheckFailure("Tests are not GREEN", report)


def require_red(report: dict) -> None:
    """Require failing assertions and reject infrastructure errors, skipped tests, or an already passing suite."""
    infrastructure_errors = ("SyntaxError", "ERR_MODULE_NOT_FOUND", "Cannot find module", "ERR_UNKNOWN_FILE_EXTENSION", "ERR_DLOPEN_FAILED")
    evidence = "\n".join(report.get("failures", [])) + "\n" + report["output"]
    if not report["returncode"] or not report.get("tests") or not report.get("fail") or report.get("skipped") or report.get("todo") or "ERR_ASSERTION" not in evidence or any(error in evidence for error in infrastructure_errors):
        raise ValueError(f"Expected assertion-based RED, not an infrastructure error or a vacuous test: {report}")


def test_run_status(report: dict) -> str:
    """Keep real GREEN/RED results; transfer server lifecycle failures to implementation."""
    if report["returncode"] == 0:
        require_green(report)
        return "GREEN"
    if re.search(r"^BACKEND_(STARTUP|RUNTIME)_ERROR:", report["output"], re.MULTILINE):
        return "REPAIR_REQUIRED"
    require_red(report)
    return "RED_CONFIRMED"
