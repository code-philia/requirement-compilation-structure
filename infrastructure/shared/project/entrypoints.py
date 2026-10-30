"""Model-selected source paths, stable exports and portable imports."""

import posixpath
from pathlib import Path, PurePosixPath
import json

from infrastructure.utils.paths import check_path_case
from infrastructure.utils.files import save_json


FILE_ROOTS = {"api": "backend/src", "page": "frontend/src", "trigger": "frontend/src",
    "backend_test": "backend/tests", "e2e_test": "frontend/tests/e2e"}


def selected_path(output: Path, kind: str, identity: str) -> str | None:
    """Read the implementation path selected for a model ID."""
    index = output / ".arc/implementation_paths.json"
    paths = json.loads(index.read_text(encoding="utf-8-sig")) if index.is_file() else {}
    return paths.get(kind, {}).get(identity)


def remember_path(output: Path, kind: str, identity: str, relative: str) -> None:
    """Remember the first edit's path without adding model response fields."""
    index = output / ".arc/implementation_paths.json"
    paths = json.loads(index.read_text(encoding="utf-8-sig")) if index.is_file() else {}
    paths.setdefault(kind, {})[identity] = relative
    save_json(index, paths)


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
