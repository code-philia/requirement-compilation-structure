"""Step 10 lowering: generate UI types, page wiring, and presence-test setup.

Compiler-owned TypeScript/configuration strings define a stable host for model-selected React components. This stage exposes UI/data only; business interactions
are designed in step 11 and installed by the interaction runtime in step 12."""

import json
from pathlib import Path
import re

from infrastructure.shared.project.entrypoints import import_path, implementation_entrypoint
from infrastructure.shared.project.initialize import enable_import_case_checks
from infrastructure.utils.files import save_text

PLAYWRIGHT_VERSION = "1.64.1"

UI_RUNTIME = '''// Compiler-owned UI types shared by presentation and interaction stages.
export interface UiPageProps { data: Readonly<Record<string, unknown>> }

declare global {
  interface Window {
    __ARC_UI_FIXTURE__?: { page: string; data: Record<string, unknown> };
  }
}

export function initialPageData(page: string, defaults: Record<string, unknown>) {
  const development = (import.meta as ImportMeta & { env: { DEV: boolean } }).env.DEV;
  const fixture = development ? window.__ARC_UI_FIXTURE__ : undefined;
  return fixture?.page === page ? { ...defaults, ...fixture.data } : defaults;
}

export function syncInput(target: EventTarget | null, bindings: Record<string, string[]>, update: (patch: Record<string, unknown>) => void) {
  if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement)) return;
  const variables = bindings[target.getAttribute("data-testid") ?? ""] ?? [];
  const value = target instanceof HTMLInputElement && target.type === "checkbox" ? target.checked : target.value;
  if (variables.length) update(Object.fromEntries(variables.map(name => [name, value])));
}

export interface UiApiRequest {
  params?: Record<string, unknown>; query?: Record<string, unknown>;
  body?: Record<string, unknown>; headers?: Record<string, string>;
  credentials?: RequestCredentials;
}
export interface UiApiResponse { status: number; body: unknown; headers: Record<string, string> }
export interface UiTriggerContext {
  readonly data: Readonly<Record<string, unknown>>;
  readonly input: { value?: string; checked?: boolean; key?: string };
  readonly trigger: { id: string; source: string; event: string };
  update(patch: Record<string, unknown>): void;
  navigate(pageId: string): void;
  api(apiId: string, request?: UiApiRequest): Promise<UiApiResponse>;
}
export type UiTriggerHandler = (context: UiTriggerContext) => void | Promise<void>;
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
    url: baseURL, reuseExistingServer: false, timeout: 30000,
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
    """Write compiler-owned UI types, application wiring, and browser-test configuration."""
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
    save_text(output / "frontend/src/ui-runtime.ts", UI_RUNTIME)


def sync_pages(output: Path, design: dict) -> None:
    """Regenerate the page registry from fixed Page exports."""
    imports, routes = ['import { useState } from "react";', 'import { initialPageData, syncInput } from "./ui-runtime";'], []
    defaults = {var: binding["initial"] for var, binding in design["bindings"].items()}
    for number, (pid, page) in enumerate(design["pages"].items()):
        entry = implementation_entrypoint(output, "page", pid)
        component = f"Page{number}"
        if entry:
            imported = import_path("frontend/src/App.tsx", entry["path"], extension="")
            imports.append(f'import {{ {entry["export"]} as {component} }} from {json.dumps(imported)};')
            body = f"<{component} data={{data}} />"
        else:
            body = '<main><h1>UI implementation pending</h1></main>'
        routes.append(f'    case {json.dumps(page["route"])}: {{\n'
            f'      const data = initialPageData({json.dumps(pid)}, state);\n'
            f'      return <div onSubmit={{event => event.preventDefault()}} onInputCapture={{event => syncInput(event.target, inputBindings, update)}} onChangeCapture={{event => syncInput(event.target, inputBindings, update)}}>{body}</div>;\n    }}')
    source = "// Compiler-owned routes and display data. UI data bindings without business triggers.\n" + "\n".join(imports)
    source += "\n\nconst defaults: Record<string, unknown> = " + json.dumps(defaults, ensure_ascii=False, indent=2) + ";\n"
    source += "\nconst inputBindings: Record<string, string[]> = " + json.dumps({uid: node["data"] for uid, node in design["elements"].items() if "user_write" in node.get("mode", []) and node.get("data")}) + ";\n"
    source += '\nexport function App() {\n  const [state, setState] = useState(defaults);\n  const update = (patch: Record<string, unknown>) => setState(current => ({ ...current, ...patch }));\n  switch (window.location.pathname) {\n' + "\n".join(routes)
    source += '\n    default: return <main><h1>Page not found</h1></main>;\n  }\n}\n'
    save_text(output / "frontend/src/App.tsx", source)
