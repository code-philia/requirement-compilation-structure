"""Workspace-relative file reading and exact local editing operations."""

from infrastructure.shared.agent.files import EXCLUDED
from infrastructure.utils.files import normalize_newlines, read_source
from infrastructure.utils.paths import check_path_case, relative_path
from difflib import get_close_matches


class FileToolError(ValueError):
    def __init__(self, code, message, path=None, **details):
        super().__init__(message)
        self.feedback = {"code": code, "message": message, **details}
        if path is not None:
            self.feedback["path"] = path


def workspace_path(root, path):
    """Translate a portable model path into a native path inside the project."""
    parts = relative_path(path).parts
    if any(part.startswith(".") or part in EXCLUDED for part in parts) or parts[:2] == ("backend", "data"):
        raise FileToolError("INVALID_PATH", "Use a project source/configuration path", path)
    check_path_case(root, path)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise FileToolError("INVALID_PATH", "Symlinks are not allowed", path)
    if not current.resolve().is_relative_to(root.resolve()):
        raise FileToolError("INVALID_PATH", "Use a file inside the working directory", path)
    if current.is_dir():
        candidates = sorted(child.relative_to(root).as_posix() for child in current.iterdir()
            if child.is_file() and not child.is_symlink() and not child.name.startswith("."))[:8]
        raise FileToolError("PATH_IS_DIRECTORY", "read_file expects a file, not a directory. Choose a concrete file path.",
            path, available_files=candidates)
    return current


def read_file(files, path, start_line=1, end_line=None):
    """Read the requested lines only; reading never expands the pinned source context."""
    target = files.path(path)
    if not files.can_read(path):
        raise FileToolError("READ_NOT_ALLOWED", "This task cannot read this file", path)
    if not target.is_file():
        candidates = files.available_paths
        if files.readable is not None:
            candidates = candidates.intersection(files.readable)
        suggested = get_close_matches(path, sorted(candidates), n=4, cutoff=0.45)
        message = "This file does not exist. Use a supplied path or one of the suggested existing files."
        raise FileToolError("FILE_NOT_FOUND", message, path, suggested_paths=suggested)
    if type(start_line) is not int or start_line < 1 or (end_line is not None and
            (type(end_line) is not int or end_line < start_line)):
        raise FileToolError("INVALID_LINE_RANGE", "Use positive, inclusive line numbers", path)
    content = read_source(target)
    lines = content.splitlines(keepends=True)
    last = min(end_line if end_line is not None else len(lines), len(lines))
    reference = None
    if files.supplied_contents.get(path) == content:
        reference = f"files[{path}]"
    else:
        for excerpt in files.read_files.get(path, []):
            if (excerpt["total_lines"] == len(lines) and excerpt["start_line"] <= start_line
                    and excerpt["end_line"] >= last
                    and excerpt["content"] == "".join(lines[excerpt["start_line"] - 1:excerpt["end_line"]])):
                reference = f"read_files[{path}]"
                break
    if reference:
        return {"path": path, "cached": True, "context_reference": reference,
            "start_line": start_line, "end_line": last, "total_lines": len(lines),
            "writable": files.can_write(path)}
    return {"path": path, "content": "".join(lines[start_line - 1:last]), "start_line": start_line,
        "end_line": last, "total_lines": len(lines), "writable": files.can_write(path)}


def edit_file(files, path, operation, new_content, old_content=""):
    """Stage a create, unique exact replacement, prepend or append in the current batch."""
    requested_target = files.path(path)
    if operation == "create" and (requested_target.exists() or path in files._pending):
        raise FileToolError("FILE_ALREADY_EXISTS", "The requested path already exists. Read it and use a local replace, prepend or append.",
            path)
    if not files.can_write(path):
        raise FileToolError("WRITE_NOT_ALLOWED", "File is outside this task's writable scope", path)
    if not isinstance(new_content, str) or not isinstance(old_content, str):
        raise FileToolError("INVALID_ARGUMENTS", "old_content and new_content must be strings", path)
    new_content, old_content = normalize_newlines(new_content), normalize_newlines(old_content)
    target = files.path(path)
    current = files._pending.get(path, read_source(target) if target.is_file() else None)
    if operation == "create":
        if current is not None:
            raise FileToolError("FILE_ALREADY_EXISTS", "This file already exists. Read and edit it locally.",
                path)
        if old_content:
            raise FileToolError("INVALID_ARGUMENTS", "create requires empty old_content", path)
        updated = new_content
    elif operation in {"replace", "prepend", "append"}:
        if current is None:
            raise FileToolError("FILE_NOT_FOUND", "Use create for a missing file", path)
        if operation == "replace":
            if not old_content:
                raise FileToolError("INVALID_ARGUMENTS", "replace requires nonempty exact old_content", path)
            if current.strip() and old_content.strip() == current.strip():
                raise FileToolError("WHOLE_FILE_REPLACEMENT_NOT_ALLOWED",
                    "Incremental compilation forbids replacing a whole existing file. "
                    "Use a smaller unique span and preserve earlier requirements, registrations and state.", path)
            first = current.find(old_content)
            count = 0 if first < 0 else (2 if current.find(old_content, first + 1) >= 0 else 1)
            if count != 1:
                raise FileToolError("OLD_CONTENT_NOT_FOUND" if count == 0 else "OLD_CONTENT_NOT_UNIQUE",
                    f"Expected exactly one old_content match, found {count}; read the relevant lines and retry", path)
            updated = current.replace(old_content, new_content, 1)
        else:
            if old_content:
                raise FileToolError("INVALID_ARGUMENTS", "Boundary insertion requires empty old_content", path)
            updated = new_content + current if operation == "prepend" else current + new_content
    else:
        raise FileToolError("INVALID_OPERATION", "Use create, replace, prepend or append", path)
    files._pending[path] = updated
    return {"path": path, "operation": operation}
