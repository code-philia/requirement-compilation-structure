"""Prepare frontend build tools and the presentation-test adapter.

Application routes, events, state and component bindings are model-owned code.
"""

import json
from pathlib import Path
import re

from infrastructure.shared.project.initialize import enable_import_case_checks
from infrastructure.utils.files import save_text

PLAYWRIGHT_VERSION = "1.64.1"
APPLICATION_ENTRYPOINTS = ("frontend/src/main.tsx", "frontend/src/App.tsx")

UI_RUNTIME = '''// Presentation-test adapter only; application behavior is implemented by the model.

declare global {
  interface Window {
    __ARC_UI_TEST_DATA__?: { page: string; data: Record<string, unknown> };
    __ARC_UI_DATA__?: { page: string; data: Readonly<Record<string, unknown>> };
  }
}

export function isPresentationTest(page: string): boolean {
  const development = (import.meta as ImportMeta & { env: { DEV: boolean } }).env.DEV;
  return development && window.__ARC_UI_TEST_DATA__?.page === page;
}

export function presentationData(page: string, state: Record<string, unknown>) {
  const development = (import.meta as ImportMeta & { env: { DEV: boolean } }).env.DEV;
  const testData = development ? window.__ARC_UI_TEST_DATA__ : undefined;
  if (development) window.__ARC_UI_DATA__ = { page, data: state };
  return testData?.page === page ? { ...state, ...testData.data } : state;
}
'''

PLAYWRIGHT_CONFIG = '''// Compiler-owned UI existence tests. No backend is started at this stage.
import { defineConfig } from "@playwright/test";

const port = Number(process.env.ARC_UI_PORT ?? "4173");
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./tests/ui",
  outputDir: "./test-results/ui",
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 20000,
  expect: { timeout: 4000 },
  reporter: "json",
  use: { baseURL, browserName: "chromium", headless: true,
    trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: {
    command: `node ../node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${port} --strictPort`,
    url: baseURL, reuseExistingServer: false, timeout: 600000,
  },
});
'''


def configure_tailwind(output: Path) -> None:
    """Enable Tailwind for existing initialized projects without replacing page code."""
    package_path = output / "frontend/package.json"
    package = json.loads(package_path.read_text(encoding="utf-8-sig"))
    dependencies = package.setdefault("devDependencies", {})
    for name in ("tailwindcss", "@tailwindcss/vite"):
        dependencies.setdefault(name, "^4.0.0")
    configuration = output / "frontend/vite.config.ts"
    source = configuration.read_text(encoding="utf-8-sig")
    if "@tailwindcss/vite" not in source:
        if "plugins: [react()]" not in source:
            raise ValueError("Enable @tailwindcss/vite in the custom frontend/vite.config.ts first")
        source = 'import tailwindcss from "@tailwindcss/vite";\n' + source.replace(
            "plugins: [react()]", "plugins: [react(), tailwindcss()]")
    stylesheet = output / "frontend/src/style.css"
    styles = stylesheet.read_text(encoding="utf-8-sig") if stylesheet.is_file() else ""
    # Remove only the original scaffold's global card layout; retain page styles.
    legacy = ('body { margin: 0; font-family: system-ui, sans-serif; color: #172033; background: #f4f6fa; }\n'
        'main { max-width: 48rem; margin: 5rem auto; padding: 2rem; background: white; border-radius: 1rem; }\n')
    if styles.startswith(legacy):
        styles = styles[len(legacy):]
    if not re.search(r'@import\s+[\'"]tailwindcss[\'"]', styles):
        styles = '@import "tailwindcss";\n' + styles
    save_text(package_path, json.dumps(package, indent=2) + "\n")
    save_text(configuration, source)
    save_text(stylesheet, styles)


def prepare_frontend(output: Path) -> None:
    """Prepare build and test infrastructure without generating application behavior."""
    for relative in ("package.json", "frontend/package.json", "frontend/src/main.tsx", "frontend/tsconfig.json", "frontend/vite.config.ts"):
        if not (output / relative).is_file():
            raise ValueError(f"Missing {relative}; run 00_project_initialization.py first")
    configure_tailwind(output)
    enable_import_case_checks(output, "frontend")
    path = output / "package.json"
    package = json.loads(path.read_text(encoding="utf-8-sig"))
    dependencies = package.setdefault("devDependencies", {})
    dependencies.setdefault("@playwright/test", PLAYWRIGHT_VERSION)
    package.setdefault("scripts", {})["test:ui"] = "playwright test --config frontend/playwright.ui.config.ts"
    save_text(path, json.dumps(package, indent=2) + "\n")
    save_text(output / "frontend/playwright.ui.config.ts", PLAYWRIGHT_CONFIG)
    adapter = output / "frontend/src/ui-runtime.ts"
    # Already accepted pages depend on this module. Stage preparation must never
    # replace its public interface beneath those pages.
    if not adapter.is_file():
        save_text(adapter, UI_RUNTIME)
