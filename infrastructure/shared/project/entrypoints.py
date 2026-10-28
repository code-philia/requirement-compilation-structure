"""Shared resolution of model-selected API and component implementation paths."""

import posixpath
from pathlib import Path
import re


def resolve_entrypoint(output: Path, index, module: str, root: str, suffixes=(".ts",), protected=()) -> dict | None:
    """Return a recorded implementation entrypoint after checking its source root, suffix, export, and protections."""
    entry = index.data["entrypoints"].get(module)
    if entry is None:
        return None
    index.validate_path(entry["path"])
    target = (output / entry["path"]).resolve()
    if not target.is_relative_to(output / root) or not target.is_file() or target.suffix not in suffixes:
        raise ValueError(f"Invalid implementation path for {module}: {entry['path']}")
    if any(target == output / path or target.is_relative_to(output / path) for path in protected):
        raise ValueError(f"Choose an implementation source, not compiler infrastructure: {module}")
    if not isinstance(entry["export"], str) or not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", entry["export"]):
        raise ValueError(f"Invalid named export for {module}")
    return dict(entry)


def import_path(source: str, target: str, extension: str = ".js") -> str:
    """Construct an import from the registering file directly to the implementation."""
    imported = posixpath.relpath(Path(target).with_suffix(extension).as_posix(), str(Path(source).parent))
    return imported if imported.startswith(".") else "./" + imported
