"""Prepare the real-server HTTP test runner; models own API wiring."""

from hashlib import sha256
import json
from pathlib import Path
import re

from infrastructure.shared.project.initialize import enable_import_case_checks
from infrastructure.utils.files import save_text


REGISTER_PATH = "backend/src/api/register.ts"
TEST_RUNNER_PATH = "backend/scripts/test-api.mjs"
TEST_SUPPORT_PATH = "backend/tests/support/context.ts"


def test_path(rid: str, aid: str) -> str:
    """Build a safe per-requirement/per-API test filename."""
    slug = rid if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", rid) else "requirement-" + sha256(rid.encode()).hexdigest()[:12]
    return f"backend/tests/{slug}/{aid}.test.ts"


def prepare_runtime(output: Path) -> None:
    """Publish fixed test infrastructure without overwriting application wiring."""
    for relative in ("package.json", "backend/package.json", "backend/src/app.ts", "backend/src/server.ts", "backend/src/api/types.ts", "backend/tsconfig.test.json"):
        if not (output / relative).is_file():
            raise ValueError(f"Missing {relative}; run main.py --stage 00 first")
    enable_import_case_checks(output, "backend")
    templates = Path(__file__).resolve().parents[2] / "shared/project/templates"
    if not (output / REGISTER_PATH).is_file():
        save_text(output / REGISTER_PATH, (templates / REGISTER_PATH).read_text(encoding="utf-8"))
    for relative in (TEST_RUNNER_PATH, TEST_SUPPORT_PATH):
        save_text(output / relative, (templates / relative).read_text(encoding="utf-8"))
    for relative, name, command in (("package.json", "test:backend", "npm run test -w @arc/backend"), ("backend/package.json", "test", "node scripts/test-api.mjs")):
        path = output / relative
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        value.setdefault("scripts", {})[name] = command
        save_text(path, json.dumps(value, indent=2) + "\n")


def api_test_paths(output: Path, api_ids=None) -> list[str]:
    """Read actual accepted/generated suites from the backend report."""
    from infrastructure.utils.files import read_artifact

    path = output / ".arc/backend_tdd.json"
    if not path.is_file():
        return []
    report = read_artifact(output / ".arc", "backend_tdd.json")
    result = set()
    for tests in report.get("tests", {}).values():
        for aid, relative in tests.items():
            if (api_ids is None or aid in api_ids) and (output / relative).is_file():
                result.add(relative)
    return sorted(result)
