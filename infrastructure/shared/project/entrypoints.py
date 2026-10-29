"""Model-selected source paths, stable exports and portable imports."""

from hashlib import sha256
import posixpath
from pathlib import Path, PurePosixPath
import re
import json

from infrastructure.utils.paths import check_path_case
from infrastructure.utils.files import save_json


FILE_ROOTS = {"api": "backend/src", "page": "frontend/src", "event": "frontend/src",
    "backend_test": "backend/tests", "e2e_test": "frontend/tests/e2e"}


def selected_path(output: Path, kind: str, identity: str) -> str | None:
    """Read a model-selected path; recognize existing convention files on resume."""
    index = output / ".arc/implementation_paths.json"
    paths = json.loads(index.read_text(encoding="utf-8-sig")) if index.is_file() else {}
    chosen = paths.get(kind, {}).get(identity)
    if chosen is not None:
        return chosen
    if kind in {"api", "page", "event"}:
        legacy = implementation_path(kind, identity)
        if (output / legacy).is_file():
            return legacy
    return None


def remember_path(output: Path, kind: str, identity: str, relative: str) -> None:
    """Remember the first edit's path without adding model response fields."""
    index = output / ".arc/implementation_paths.json"
    paths = json.loads(index.read_text(encoding="utf-8-sig")) if index.is_file() else {}
    paths.setdefault(kind, {})[identity] = relative
    save_json(index, paths)


def implementation_path(kind: str, identity: str) -> str:
    """Recognize legacy filenames for existing outputs; new filenames are model-selected."""
    directory, suffix = {"api": ("backend/src/handlers", ".ts"),
        "page": ("frontend/src/pages", ".tsx"), "event": ("frontend/src/events", ".ts")}[kind]
    if not isinstance(identity, str) or not identity:
        raise ValueError("Implementation IDs must be nonempty strings")
    slug = re.sub(r"[^a-z0-9_-]", "-", identity.lower())[:40]
    name = f"module-{slug}-{sha256(identity.encode()).hexdigest()[:16]}"
    return f"{directory}/{name}{suffix}"


def implementation_entrypoint(output: Path, kind: str, identity: str) -> dict | None:
    """Resolve the selected path; TypeScript checks the stable named export."""
    relative = selected_path(output, kind, identity)
    if relative is None:
        return None
    check_path_case(output, relative)
    current = output
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Implementation path must not contain symlinks: {relative}")
    if not current.is_file():
        return None
    return {"path": relative, "export": "Page" if kind == "page" else "handle"}


def import_path(source: str, target: str, extension: str = ".js") -> str:
    """Construct a portable import directly to the selected implementation file."""
    imported = posixpath.relpath(PurePosixPath(target).with_suffix(extension).as_posix(), PurePosixPath(source).parent.as_posix())
    return imported if imported.startswith(".") else "./" + imported
