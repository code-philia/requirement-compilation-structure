"""Step 08 lowering: render backend registration and stable test bindings.

Source strings below are compiler-owned TypeScript templates, not model output.
Business API implementations are selected through file_index.json entrypoints;
registration imports those files directly instead of creating per-API proxies."""

from hashlib import sha256
import json
import posixpath
from pathlib import Path
import re

from infrastructure.shared.project.entrypoints import import_path, resolve_entrypoint
from infrastructure.shared.project.initialize import enable_import_case_checks
from infrastructure.utils.files import save_text


REGISTER_PATH = "backend/src/api/register.ts"
TEST_BINDINGS_PATH = "backend/tests/support/apis.ts"
PROTECTED = ("backend/src/db", "backend/src/api/types.ts", REGISTER_PATH,
    "backend/src/app.ts", "backend/src/server.ts")


def test_path(rid: str, aid: str) -> str:
    """Build a safe per-requirement/per-API test filename, hashing IDs that are unsuitable for paths."""
    slug = rid if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", rid) else "requirement-" + sha256(rid.encode()).hexdigest()[:12]
    return f"backend/tests/{slug}/{aid}.test.ts"


def api_entrypoint(output: Path, index, aid: str) -> dict | None:
    """Resolve the selected API implementation under backend/src while excluding compiler-owned wiring."""
    return resolve_entrypoint(output, index, f"backend:{aid}", "backend/src", protected=PROTECTED)


def test_bindings_source(output: Path, apis: dict, index, stubbed=()) -> str:
    """The stable TDD imports live only in tests, never in the runtime source tree."""
    lines = ["// Compiler-owned test bindings; routing imports implementations directly.",
        'import type Database from "better-sqlite3";',
        'import type { ApiRequest, ApiResponse } from "../../src/api/types.js";']
    for aid, api in apis.items():
        entry = api_entrypoint(output, index, aid)
        name = api["signature"]["name"]
        if entry is not None and aid not in stubbed:
            imported = import_path(TEST_BINDINGS_PATH, entry["path"])
            lines.append(f'export {{ {entry["export"]} as {name} }} from {json.dumps(imported)};')
        else:
            lines.extend([f'export async function {name}(_request: ApiRequest, _connection: Database.Database): Promise<ApiResponse> {{',
                '  return { status: 501, body: { error: "Not implemented" } };', '}'])
    return "\n".join([*lines, ""])


def sync_implementations(output: Path, apis: dict, index, requirements: dict) -> None:
    """Register each API from its chosen file and update the test-only bindings."""
    save_text(output / REGISTER_PATH, register_source(apis, output, index))
    save_text(output / TEST_BINDINGS_PATH, test_bindings_source(output, apis, index))
    for aid in apis:
        entry = api_entrypoint(output, index, aid)
        uses = [rid for rid, ids in requirements.items() if aid in ids]
        paths = [REGISTER_PATH, "backend/src/app.ts", "backend/src/server.ts"]
        if entry is not None:
            paths.append(entry["path"])
        index.record(paths, uses, f"backend:{aid}")
        index.record([TEST_BINDINGS_PATH], uses, f"tests:{aid}")


def register_source(apis: dict, output: Path, index) -> str:
    """Render Express registration that imports selected implementations and checks contract request/response shapes."""
    lines = ['import type { Express } from "express";', 'import type Database from "better-sqlite3";',
        'import type { ApiRequest, ApiResponse } from "./types.js";']
    for number, (aid, api) in enumerate(apis.items()):
        entry = api_entrypoint(output, index, aid)
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


def prepare_runtime(output: Path, apis: dict, index, requirements: dict) -> None:
    """Write shared backend wiring and test bindings, track their owners, and migrate recognized legacy adapters."""
    for relative in ("package.json", "backend/package.json", "backend/src/app.ts", "backend/src/server.ts", "backend/src/api/types.ts", "backend/tests/support/context.ts", "backend/tsconfig.test.json"):
        if not (output / relative).is_file():
            raise ValueError(f"Missing {relative}; run 00_project_initialization.py first")
    index.record([enable_import_case_checks(output, "backend")], [], "project:backend")
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
    migrate_legacy_adapters(output, apis, index, requirements)
    sync_implementations(output, apis, index, requirements)
    for relative, name, command in (("package.json", "test:backend", "npm run test -w @arc/backend"), ("backend/package.json", "test", "node scripts/test-api.mjs")):
        path = output / relative
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        existing = value.setdefault("scripts", {}).get(name)
        if existing not in (None, command):
            raise ValueError(f"Existing {name} command differs; keep a separate API test command")
        value["scripts"][name] = command
        save_text(path, json.dumps(value, indent=2) + "\n")


def migrate_legacy_adapters(output: Path, apis: dict, index, requirements: dict) -> None:
    """Retire only recognized compiler proxies and rewrite their test imports."""
    retired = []
    for aid, api in apis.items():
        relative = f"backend/src/api/{aid}.ts"
        if relative in PROTECTED:
            continue
        target = output / relative
        if not target.is_file():
            continue
        source = target.read_text(encoding="utf-8-sig")
        proxy = re.fullmatch(r'// Compiler-owned adapter for a model-selected implementation\.\s*export \{ ([A-Za-z_$][A-Za-z0-9_$]*) as ([A-Za-z_$][A-Za-z0-9_$]*) \} from ([\'"])([^\'"]+)\3;\s*', source)
        module = f"backend:{aid}"
        if module not in index.data["entrypoints"]:
            if proxy:
                implementation = (target.parent / proxy.group(4)).with_suffix(".ts").resolve()
                entry = {"path": implementation.relative_to(output).as_posix(), "export": proxy.group(1)}
            else:
                # Earlier single-file implementations remain legitimate chosen paths.
                entry = {"path": relative, "export": api["signature"]["name"]}
            uses = [rid for rid, ids in requirements.items() if aid in ids]
            index.record([entry["path"]], uses, module, entry)
        entry = api_entrypoint(output, index, aid)
        if proxy and entry["path"] != relative:
            retired.append(relative)
    for test in (output / "backend/tests").rglob("*.test.ts"):
        source = test.read_text(encoding="utf-8-sig")
        changed = source
        for aid in apis:
            old = f"backend/src/api/{aid}.js"
            def replace(match):
                """Rewrite a recognized legacy test import to the stable compiler-owned test binding."""
                imported = posixpath.normpath(posixpath.join(test.relative_to(output).parent.as_posix(), match.group(2)))
                if imported != old:
                    return match.group(0)
                new = import_path(test.relative_to(output).as_posix(), TEST_BINDINGS_PATH)
                return f"from {match.group(1)}{new}{match.group(1)}"
            changed = re.sub(r"\bfrom\s+(['\"])([^'\"]+)\1", replace, changed)
        if changed != source:
            save_text(test, changed)
    if retired:
        index.forget_files(retired)
    for relative in retired:
        (output / relative).unlink()
        compiled = output / relative.replace("backend/src/", "backend/dist/", 1)
        compiled = compiled.with_suffix(".js")
        if compiled.is_file() and compiled.read_text(encoding="utf-8-sig").startswith("// Compiler-owned adapter for a model-selected implementation."):
            compiled.unlink()
