"""Fixed test commands, contract traceability checks, and immutable test snapshots."""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from infrastructure.utils.processes import capture_process
from infrastructure.utils.files import save_bytes


def condition_tokens(api: dict) -> set[str]:
    """Collect P/Q condition IDs and R/W field tokens that test titles must trace."""
    return {item["id"] for kind in ("precondition", "postcondition") for item in api[kind]} | {f"R:{field}" for field in api["read"]} | {f"W:{field}" for field in api["write"]}


def test_budget(api: dict, maximum: int = 5) -> int:
    """Choose a small test-case budget while ensuring all declared response branches can be covered."""
    if maximum < 1:
        raise ValueError("--max-tests must be positive")
    branches = 1 + len(api["response"]["errors"])
    if branches > maximum:
        raise ValueError(f"This contract declares {branches} response branches; increase --max-tests to cover them")
    return min(maximum, max(2, branches, 1 + len(api["precondition"])))


def validate_test_source(source: str, api: dict, maximum: int | None = None) -> None:
    """Check literal test cases, traceability tokens, meaningful assertions, and the case budget before executing tests."""
    titles = re.findall(r"\btest\(\s*(['\"])(.*?)\1\s*,", source, re.DOTALL)
    if not titles or not re.search(r"from\s+['\"]node:test['\"]", source) or "node:assert/strict" not in source:
        raise ValueError("Use named literal test(...) cases with node:test and node:assert/strict")
    if maximum is not None and len(titles) > maximum:
        raise ValueError(f"Keep at most {maximum} key contract tests; combine related assertions and remove input variations")
    if re.search(r"\b(?:test|describe)\.(?:skip|todo|only)\b|\bmock\s*\(|process\.exit", source):
        raise ValueError("Tests may not be skipped, focused, mocked, or exit early")
    names = "\n".join(title for _, title in titles)
    missing = [token for token in sorted(condition_tokens(api)) if not re.search(r"(?<![A-Za-z0-9_.:-])" + re.escape(token) + r"(?![A-Za-z0-9_.:-])", names)]
    if missing:
        raise ValueError(f"Test titles must trace every P/Q and R/W obligation; missing: {missing}")
    if not re.search(r"\bassert\.(?:equal|deepEqual|ok|match|notEqual|throws|rejects|strictEqual|deepStrictEqual)\s*\(", source):
        raise ValueError("Contract tests must assert observable results")


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
    """Reject a test report unless the selected suite passed without skips."""
    if report["returncode"] != 0 or not report.get("tests") or report.get("fail") or report.get("skipped") or report.get("todo"):
        raise ValueError(f"Tests are not GREEN: {report}")


def require_red(report: dict) -> None:
    """Require failing assertions and reject infrastructure errors, skipped tests, or an already passing suite."""
    infrastructure_errors = ("SyntaxError", "ERR_MODULE_NOT_FOUND", "Cannot find module", "ERR_UNKNOWN_FILE_EXTENSION", "ERR_DLOPEN_FAILED")
    if not report["returncode"] or not report.get("tests") or not report.get("fail") or report.get("skipped") or report.get("todo") or "ERR_ASSERTION" not in report["output"] or any(error in report["output"] for error in infrastructure_errors):
        raise ValueError(f"Expected assertion-based RED, not an infrastructure error or a vacuous test: {report}")


def snapshot_tests(output: Path, files: list[str] | None = None) -> dict:
    """Snapshot accepted test and support-file bytes, excluding the compiler-regenerated API bindings."""
    paths = (output / "backend/tests").rglob("*.ts") if files is None else [
        *(output / relative for relative in files),
        *(path for path in (output / "backend/tests/support").rglob("*.ts") if path.name != "apis.ts"),
    ]
    # apis.ts is regenerated by the compiler as fixed implementation files become available; assertions
    # and fixture helpers remain frozen. Models cannot edit test support.
    return {path.relative_to(output).as_posix(): path.read_bytes() for path in paths if path != output / "backend/tests/support/apis.ts"}


def assert_frozen(output: Path, snapshot: dict) -> None:
    """Restore changed trusted test files and reject implementation that altered the accepted assertions."""
    if any(not (output / relative).is_file() or (output / relative).read_bytes() != content for relative, content in snapshot.items()):
        # Restore trusted test text before reporting the rejected execution.
        for relative, content in snapshot.items():
            (output / relative).parent.mkdir(parents=True, exist_ok=True)
            save_bytes(output / relative, content)
        raise ValueError("Frozen tests were modified during implementation")
