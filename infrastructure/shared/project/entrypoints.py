"""Deterministic implementation paths, fixed exports and portable imports."""

from hashlib import sha256
import posixpath
from pathlib import Path, PurePosixPath
import re

from infrastructure.utils.paths import check_path_case


def implementation_path(kind: str, identity: str) -> str:
    """Use readable, portable filenames with a stable suffix for normalized/case-only IDs."""
    directory, suffix = {"api": ("backend/src/handlers", ".ts"),
        "page": ("frontend/src/pages", ".tsx"), "event": ("frontend/src/events", ".ts")}[kind]
    if not isinstance(identity, str) or not identity:
        raise ValueError("Implementation IDs must be nonempty strings")
    slug = re.sub(r"[^a-z0-9_-]", "-", identity.lower())[:40]
    name = f"module-{slug}-{sha256(identity.encode()).hexdigest()[:16]}"
    return f"{directory}/{name}{suffix}"


def implementation_entrypoint(output: Path, kind: str, identity: str) -> dict | None:
    """Resolve only the convention path; TypeScript checks the fixed named export."""
    relative = implementation_path(kind, identity)
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
    """Construct a portable import directly to the fixed implementation file."""
    imported = posixpath.relpath(PurePosixPath(target).with_suffix(extension).as_posix(), PurePosixPath(source).parent.as_posix())
    return imported if imported.startswith(".") else "./" + imported
