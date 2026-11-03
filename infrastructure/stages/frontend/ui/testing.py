"""Deterministic UI existence suites and bounded browser/typecheck commands."""

from infrastructure.shared.agent.feedback import CheckFailure

import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile

from infrastructure.stages.frontend.ui.design import data_symbols, page_elements, visible
from infrastructure.utils.processes import capture_process, npm_command

KEY_TYPES = {"page", "form", "input", "checkbox", "select", "button", "heading", "link", "list", "image", "alert", "table", "text"}


def presentation_run_status(result):
    """Repair existing page runtime failures; only assertion failures establish valid RED."""
    if result["returncode"] == 0:
        require_green(result)
        return "GREEN"
    headlines = [message.split("\n", 1)[0] for message in result.get("failures", [])]
    if not result.get("errors") and not result.get("skipped") and not result.get("flaky") and result.get("failed") and any("UI_RUNTIME_ERROR" in message or "UI_BUSINESS_CALL" in message for message in headlines):
        return "REPAIR_REQUIRED"
    require_red(result)
    return "RED_CONFIRMED"


def test_path(pid: str) -> str:
    """Return a stable, filesystem-safe Playwright spec path for a page ID."""
    return f"frontend/tests/ui/{pid}.spec.ts"


def existence_suite(design: dict, pid: str) -> str:
    """Supply test-local display data; check controls and actual application data keys."""
    page = design["pages"][pid]
    elements = page_elements(design, pid)
    variables = data_symbols(elements)
    empty_values = {"string": "", "integer": 0, "number": 0, "boolean": False,
        "array": [], "object": {}, "null": None}
    values = {}
    for name, declaration in variables.items():
        values[name] = empty_values[declaration["dtype"]]

    # Exercise conditional controls using values owned only by this generated test.
    states = [values]
    for uid in elements:
        overrides = {}
        current, seen = uid, set()
        possible = True
        while current in elements and current not in seen:
            seen.add(current)
            node = elements[current]
            rule = node.get("prop", {}).get("visible", True)
            if rule is False:
                possible = False
                break
            if isinstance(rule, dict):
                name, expected = rule["var"], rule["equals"]
                if name in overrides and overrides[name] != expected:
                    possible = False
                    break
                overrides[name] = expected
            current = node.get("parent")
        candidate = {**values, **overrides}
        if possible and candidate not in states:
            states.append(candidate)

    lines = ['// Compiler-owned presence tests. Display values belong to this suite only.',
        'import { test, expect } from "@playwright/test";', '']
    for number, state in enumerate(states, 1):
        lines.append(f'test({json.dumps(pid + " / display " + str(number) + " / UI element existence")}, async ({{ page }}) => {{')
        lines.extend([
            '  const runtimeErrors: string[] = [];',
            '  page.on("pageerror", error => runtimeErrors.push(error.message));',
            '  await page.addInitScript(testData => { (window as unknown as { __ARC_UI_TEST_DATA__: unknown }).__ARC_UI_TEST_DATA__ = testData; }, '
                + json.dumps({"page": pid, "data": state}, ensure_ascii=False) + ');',
            f'  await page.goto({json.dumps(page["route"])});',
            '  if (runtimeErrors.length) throw new Error("UI_RUNTIME_ERROR: " + runtimeErrors.join("\\n"));',
            '  try {',
        ])
        for uid, node in elements.items():
            kind = node.get("type", "page" if uid == page["root"] else "container")
            if kind not in KEY_TYPES:
                continue
            locator = f"page.getByTestId({json.dumps(uid)})"
            shown = visible(design, uid, state)
            lines.append(f"  await expect({locator}){'' if shown else '.not'}.toBeVisible();")
        lines.extend([
            '  await expect.poll(() => page.evaluate(({ pageId, keys }) => {',
            '    const state = (window as unknown as { __ARC_UI_DATA__?: { page: string; data: Record<string, unknown> } }).__ARC_UI_DATA__;',
            '    return state?.page === pageId && keys.every(key => Object.prototype.hasOwnProperty.call(state.data, key));',
            '  }, ' + json.dumps({"pageId": pid, "keys": sorted(variables)}) + ')).toBe(true);',
            '  } catch (error) {',
            '    if (runtimeErrors.length) throw new Error("UI_RUNTIME_ERROR: " + runtimeErrors.join("\\n"));',
            '    throw error;',
            '  }',
            '  if (runtimeErrors.length) throw new Error("UI_RUNTIME_ERROR: " + runtimeErrors.join("\\n"));',
            '});', '',
        ])
    return "\n".join(lines)


def require_green(result: dict) -> None:
    """Require passing actual browser assertions with no reported runtime errors."""
    if result["returncode"] or result.get("errors") or not result.get("passed") or result.get("failed"):
        raise CheckFailure("UI checks are not GREEN", result)


def require_red(result: dict) -> None:
    """Require missing-component assertion failures rather than browser, server, or application runtime failures."""
    errors = result.get("failures", [])
    excluded = ("UI_RUNTIME_ERROR", "UI_BUSINESS_CALL", "ERR_", "browserType.launch", "page.goto:", "SyntaxError", "ReferenceError", "Cannot find module")
    # Code frames can contain the literal runtime-guard text from adjacent lines;
    # classify the actual error headline rather than those source snippets.
    headlines = [re.sub(r"\x1b\[[0-9;]*m", "", message).split("\n", 1)[0] for message in errors]
    if not result["returncode"] or not result.get("failed") or result.get("errors") or not errors or any(not re.search(r"expect\(|AssertionError", message) or any(word in message for word in excluded) for message in headlines):
        raise ValueError(f"Expected missing-component assertion RED, not infrastructure/runtime failure: {result}")


def parse_playwright_result(result: dict, include_files: bool = False) -> dict:
    """Parse the Playwright JSON reporter into counts, failures, runtime errors, and optional per-file totals."""
    try:
        report = json.loads(result.pop("stdout"))
    except (ValueError, KeyError) as error:
        raise ValueError(f"Playwright did not return its JSON report: {result['output']}") from error
    failures = []
    files = {}

    def visit(suite):
        """Accumulate nested Playwright suite/spec results into the normalized browser-check report."""
        for spec in suite.get("specs", []):
            filename = spec.get("file", suite.get("file", ""))
            files[filename] = files.get(filename, 0) + len(spec.get("tests", []))
            for test in spec.get("tests", []):
                for run in test.get("results", []):
                    if run.get("status") not in {"passed", "skipped"}:
                        failures.append("\n".join(item.get("message", "") for item in run.get("errors", [])) + "\nTest file: " + filename)
        for child in suite.get("suites", []):
            visit(child)

    for suite in report.get("suites", []):
        visit(suite)
    stats = report.get("stats", {})
    if isinstance(stats.get("duration"), (int, float)):
        result["test_seconds"] = stats["duration"] / 1000
    result.update({"passed": stats.get("expected", 0), "failed": stats.get("unexpected", 0),
        "skipped": stats.get("skipped", 0), "flaky": stats.get("flaky", 0),
        "errors": report.get("errors", []), "failures": failures})
    if include_files:
        result["files"] = files
    result["output"] = json.dumps({key: value for key, value in result.items() if key != "output"}, ensure_ascii=False, indent=2)[-24000:]
    return result


class FrontendChecks:
    """Compiler-owned browser installation, TypeScript, Playwright, and workspace build commands."""
    def __init__(self, output: Path, timeout: int = 600) -> None:
        """Bind browser/build checks to the generated workspace and locate Node.js and npm."""
        self.output, self.timeout = output.resolve(), timeout
        self.node = shutil.which("node")
        if not self.node:
            raise ValueError("Node.js is required for UI checks")
        self.node = str(Path(self.node).resolve())

    def execute(self, args: list[str], timeout: int | None = None, env: dict | None = None, executable: str | None = None) -> dict:
        """Run a fixed check command, capture its output, and stop its process group on timeout or interruption."""
        try:
            return capture_process([executable or self.node, *args], cwd=self.output,
                timeout=timeout or self.timeout, env=env)
        except subprocess.TimeoutExpired as error:
            raise ValueError(f"Frontend check timed out after {timeout or self.timeout}s") from error

    def install_browser(self) -> None:
        """Install the Chromium browser used by the generated Playwright tests."""
        result = self.execute(["node_modules/@playwright/test/cli.js", "install", "chromium"], timeout=600)
        print(result["output"], flush=True)
        if result["returncode"]:
            raise ValueError("Playwright Chromium installation failed; install its OS libraries if reported above")

    def typecheck(self, files: list[str], *, test_roots=("frontend/tests/ui",), source_files=("src/**/*.ts", "src/**/*.tsx")) -> dict:
        """Compile selected frontend/test roots with a temporary TypeScript configuration, then remove that configuration."""
        includes = list(source_files)
        for relative in files:
            path = (self.output / relative).resolve()
            if not any(path.is_relative_to(self.output / root) for root in test_roots):
                raise ValueError("Typecheck only the supplied frontend test roots")
            includes.append(path.relative_to(self.output / "frontend").as_posix())
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", suffix=".json", prefix=".tsconfig-ui-", dir=self.output / "frontend", delete=False) as config:
            path = Path(config.name)
            json.dump({"extends": "./tsconfig.json", "compilerOptions": {"types": ["vite/client", "node"], "forceConsistentCasingInFileNames": True}, "include": includes}, config)
        try:
            result = self.execute(["node_modules/typescript/bin/tsc", "--noEmit", "-p", str(path)])
            result.pop("stdout", None)
            return result
        finally:
            path.unlink(missing_ok=True)

    def tests(self, files: list[str]) -> dict:
        """Run selected UI-existence specs with Playwright and normalize the reporter output."""
        if not files:
            raise ValueError("Do not run an empty UI suite")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = {**os.environ, "ARC_UI_PORT": str(port)}
        result = self.execute(["node_modules/@playwright/test/cli.js", "test", "--config", "frontend/playwright.ui.config.ts", *files], env=env)
        return parse_playwright_result(result)

    def build(self) -> dict:
        """Run the generated workspace's frontend and backend build command and return the captured result."""
        command = npm_command()
        return self.execute([*command[1:], "run", "build"], executable=command[0])
