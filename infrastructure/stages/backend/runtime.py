"""Step 08 lowering: render backend registration and stable test bindings.

Source strings below are compiler-owned TypeScript templates, not model output.
Business API implementations use model-selected files and a stable handle export;
registration imports those files directly instead of creating per-API proxies."""

from hashlib import sha256
import json
from pathlib import Path
import re

from infrastructure.shared.project.entrypoints import import_path, implementation_entrypoint
from infrastructure.shared.project.initialize import enable_import_case_checks
from infrastructure.utils.files import save_text


REGISTER_PATH = "backend/src/api/register.ts"
TEST_BINDINGS_PATH = "backend/tests/support/apis.ts"


def test_path(rid: str, aid: str) -> str:
    """Build a safe per-requirement/per-API test filename, hashing IDs that are unsuitable for paths."""
    slug = rid if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", rid) else "requirement-" + sha256(rid.encode()).hexdigest()[:12]
    return f"backend/tests/{slug}/{aid}.test.ts"


def api_entrypoint(output: Path, aid: str) -> dict | None:
    """Resolve the selected API implementation file and handle export."""
    return implementation_entrypoint(output, "api", aid)


def test_bindings_source(output: Path, apis: dict, stubbed=()) -> str:
    """The stable TDD imports live only in tests, never in the runtime source tree."""
    lines = ["// Compiler-owned test bindings; routing imports implementations directly.",
        'import type Database from "better-sqlite3";',
        'import type { ApiRequest, ApiResponse } from "../../src/api/types.js";']
    for aid, api in apis.items():
        entry = api_entrypoint(output, aid)
        name = api["signature"]["name"]
        if entry is not None and aid not in stubbed:
            imported = import_path(TEST_BINDINGS_PATH, entry["path"])
            lines.append(f'export {{ {entry["export"]} as {name} }} from {json.dumps(imported)};')
        else:
            lines.extend([f'export async function {name}(_request: ApiRequest, _connection: Database.Database): Promise<ApiResponse> {{',
                '  return { status: 501, body: { error: "Not implemented" } };', '}'])
    return "\n".join([*lines, ""])


def sync_implementations(output: Path, apis: dict) -> None:
    """Register selected API files and refresh test-only bindings."""
    save_text(output / REGISTER_PATH, register_source(apis, output))
    save_text(output / TEST_BINDINGS_PATH, test_bindings_source(output, apis))


def register_source(apis: dict, output: Path) -> str:
    """Render Express registration that imports selected implementations directly."""
    lines = ['import type { Express } from "express";', 'import type Database from "better-sqlite3";',
        'import type { ApiRequest, ApiResponse } from "./types.js";']
    for number, (aid, api) in enumerate(apis.items()):
        entry = api_entrypoint(output, aid)
        if entry is not None:
            imported = import_path(REGISTER_PATH, entry["path"])
            lines.append(f'import {{ {entry["export"]} as handler{number} }} from {json.dumps(imported)};')
        else:
            # No per-API placeholder file is created. Unimplemented routes return 501.
            lines.append(f'const handler{number} = async (_request: ApiRequest, _connection: Database.Database): Promise<ApiResponse> => ({{ status: 501, body: {{ error: "Not implemented" }} }});')
    lines.append('\nexport function registerApis(app: Express, connection: Database.Database): void {')
    for number, api in enumerate(apis.values()):
        signature = api["signature"]
        lines.extend([
            f'  app.{signature["method"].lower()}({json.dumps(signature["path"])}, async (req, res, next) => {{',
            '    try {',
            f'      const result = await handler{number}({{',
            '        params: Object.fromEntries(Object.entries(req.params).map(([key, value]) => [key, String(value)])),',
            '        query: req.query, body: req.body ?? {},',
            '        headers: Object.fromEntries(Object.entries(req.headers).map(([key, value]) => [key, Array.isArray(value) ? value.join("; ") : value])),',
            '      }, connection);',
            '      for (const [key, value] of Object.entries(result.headers ?? {})) res.setHeader(key, value);',
            '      res.status(result.status).json(result.body);',
            '    } catch (error) { next(error); }',
            '  });',
        ])
    return "\n".join([*lines, '}', ''])


def prepare_runtime(output: Path, apis: dict) -> None:
    """Write shared backend wiring and fixed test bindings."""
    for relative in ("package.json", "backend/package.json", "backend/src/app.ts", "backend/src/server.ts", "backend/src/api/types.ts", "backend/tests/support/context.ts", "backend/tsconfig.test.json"):
        if not (output / relative).is_file():
            raise ValueError(f"Missing {relative}; run 00_project_initialization.py first")
    enable_import_case_checks(output, "backend")
    # Upgrade the original teaching scaffold through its stable extension seam.
    # Unknown custom layouts are reported rather than replacing application code.
    app = output / "backend/src/app.ts"
    source = app.read_text(encoding="utf-8-sig")
    if 'import { registerApis }' not in source:
        marker = '  // Later backend passes add business routes before this API fallback.'
        if "export function createApp() {" not in source or marker not in source:
            raise ValueError("Expose createApp(connection) and mount registerApis before the API fallback")
        source = 'import type Database from "better-sqlite3";\nimport { registerApis } from "./api/register.js";\n' + source
        source = source.replace("export function createApp() {", "export function createApp(connection?: Database.Database) {")
        source = source.replace(marker, '  if (connection) registerApis(app, connection);\n' + marker)
        save_text(app, source)
    server = output / "backend/src/server.ts"
    source = server.read_text(encoding="utf-8-sig")
    if "createApp().listen(" in source:
        save_text(server, source.replace("createApp().listen(", "createApp(connection).listen("))
    sync_implementations(output, apis)
    for relative, name, command in (("package.json", "test:backend", "npm run test -w @arc/backend"), ("backend/package.json", "test", "node scripts/test-api.mjs")):
        path = output / relative
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        value.setdefault("scripts", {})[name] = command
        save_text(path, json.dumps(value, indent=2) + "\n")
