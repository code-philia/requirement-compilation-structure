"""Prepare backend infrastructure and test aliases; models own HTTP wiring."""

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
    """Refresh test-only bindings without overwriting application wiring."""
    save_text(output / TEST_BINDINGS_PATH, test_bindings_source(output, apis))


def prepare_runtime(output: Path, apis: dict) -> None:
    """Prepare test bindings and create a registry only when absent."""
    for relative in ("package.json", "backend/package.json", "backend/src/app.ts", "backend/src/server.ts", "backend/src/api/types.ts", "backend/tests/support/context.ts", "backend/tsconfig.test.json"):
        if not (output / relative).is_file():
            raise ValueError(f"Missing {relative}; run 00_project_initialization.py first")
    enable_import_case_checks(output, "backend")
    if not (output / REGISTER_PATH).is_file():
        template = Path(__file__).resolve().parents[2] / "shared/project/templates" / REGISTER_PATH
        save_text(output / REGISTER_PATH, template.read_text(encoding="utf-8"))
    sync_implementations(output, apis)
    for relative, name, command in (("package.json", "test:backend", "npm run test -w @arc/backend"), ("backend/package.json", "test", "node scripts/test-api.mjs")):
        path = output / relative
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        value.setdefault("scripts", {})[name] = command
        save_text(path, json.dumps(value, indent=2) + "\n")
