"""Portable workspace-relative paths, distinct from native absolute filesystem paths."""

from pathlib import PurePosixPath, PureWindowsPath
import re

RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
    *(f"COM{i}" for i in "123456789¹²³"), *(f"LPT{i}" for i in "123456789¹²³")}


def relative_path(value: str) -> PurePosixPath:
    """Require canonical forward-slash paths that are valid on Linux and Windows."""
    if not isinstance(value, str) or not value or "\\" in value or PureWindowsPath(value).drive:
        raise ValueError("Use workspace-relative paths with forward slashes, without a drive or backslashes")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(part in {".", ".."} for part in path.parts):
        raise ValueError("Use a canonical workspace-relative path without parent traversal")
    for part in path.parts:
        if re.search(r'[<>:"|?*\x00-\x1f]', part) or part.endswith((".", " ")) or part.split(".")[0].rstrip(" ").upper() in RESERVED_NAMES:
            raise ValueError(f"Unsupported workspace path component: {part}; choose another name")
    return path


def check_path_case(root, relative: str) -> None:
    """Reject case-only aliases/collisions instead of producing imports that fail on another OS."""
    current = root
    for part in relative_path(relative).parts:
        if not current.is_dir():
            break
        matches = [entry.name for entry in current.iterdir() if entry.name.casefold() == part.casefold()]
        if matches and (part not in matches or len(matches) > 1):
            raise ValueError(f"Use one exact path spelling/case: {relative}; existing: {matches}")
        current = current / part
