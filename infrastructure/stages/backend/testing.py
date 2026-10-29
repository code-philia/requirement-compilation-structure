"""Execute actual backend compilation and tests without source/title policy gates."""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from infrastructure.utils.processes import capture_process


class BackendChecks:
    """Compiler-owned TypeScript and Node test commands; generated code cannot choose shell commands."""
    def __init__(self, output: Path, timeout: int = 120) -> None:
        """Bind fixed backend check commands to the generated workspace and require an available Node.js executable."""
        self.output = output.resolve()
        self.timeout = timeout
        self.node = shutil.which("node")
        if self.node:
            self.node = str(Path(self.node).resolve())
        if not self.node or not (self.output / "node_modules/typescript/bin/tsc").is_file() or not (self.output / "node_modules/tsx").is_dir():
            raise ValueError("Node.js and workspace dev dependencies (typescript/tsx) are required for backend checks")

    def execute(self, argv: list[str]) -> dict:
        """Run a fixed Node command in the workspace and return its exit code and captured output."""
        try:
            result = capture_process([self.node, *argv], cwd=self.output, timeout=self.timeout)
        except subprocess.TimeoutExpired as error:
            raise ValueError(f"Backend check timed out after {self.timeout}s") from error
        return {"returncode": result["returncode"], "output": result["output"]}

    def typecheck(self, files: list[str] | None = None) -> dict:
        """Compile selected backend tests with TypeScript, using and cleaning a temporary test configuration."""
        if files is None:
            return self.execute(["node_modules/typescript/bin/tsc", "--noEmit", "-p", "backend/tsconfig.test.json"])
        # Imported API modules and helpers are included by TypeScript. Future
        # requirements' tests and the global registry must not enter this gate.
        includes = []
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
        """Run selected API test files with the fixed Node test command and parse its TAP counts."""
        if not files:
            return {"returncode": 0, "output": "No tests for this empty API set.", "tests": 0, "pass": 0, "fail": 0}
        result = self.execute(["--import", "tsx", "--test", "--test-reporter=tap", *files])
        for kind in ("tests", "pass", "fail", "skipped", "todo"):
            found = re.search(rf"^# {kind} (\d+)\s*$", result["output"], re.MULTILINE)
            result[kind] = int(found.group(1)) if found else 0
        return result


def require_green(report: dict) -> None:
    """Reject a test report unless the selected suite passed."""
    if report["returncode"] != 0 or not report.get("tests") or report.get("fail"):
        raise ValueError(f"Tests are not GREEN: {report}")


def require_red(report: dict) -> None:
    """Require failing assertions and reject infrastructure errors, skipped tests, or an already passing suite."""
    infrastructure_errors = ("SyntaxError", "ERR_MODULE_NOT_FOUND", "Cannot find module", "ERR_UNKNOWN_FILE_EXTENSION", "ERR_DLOPEN_FAILED")
    if not report["returncode"] or not report.get("tests") or not report.get("fail") or "ERR_ASSERTION" not in report["output"] or any(error in report["output"] for error in infrastructure_errors):
        raise ValueError(f"Expected assertion-based RED, not an infrastructure error or a vacuous test: {report}")
