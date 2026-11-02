"""Workspace-relative file reading and exact local editing operations."""

from infrastructure.shared.agent.files import EXCLUDED
from infrastructure.utils.files import normalize_newlines, read_source
from infrastructure.utils.paths import check_path_case, relative_path


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
    if not current.resolve().is_relative_to(root.resolve()) or current.is_dir():
        raise FileToolError("INVALID_PATH", "Use a file inside the working directory", path)
    return current


def read_file(files, path, start_line=1, end_line=None):
    """Read the requested lines only; reading never expands the pinned source context."""
    target = files.path(path)
    if files.readable is not None and path not in files.readable:
        raise FileToolError("READ_NOT_ALLOWED", "This task cannot read this file", path)
    if not target.is_file():
        raise FileToolError("FILE_NOT_FOUND", "File does not exist; use edit_file/create for a new file", path)
    if type(start_line) is not int or start_line < 1 or (end_line is not None and
            (type(end_line) is not int or end_line < start_line)):
        raise FileToolError("INVALID_LINE_RANGE", "Use positive, inclusive line numbers", path)
    lines = read_source(target).splitlines(keepends=True)
    last = min(end_line if end_line is not None else len(lines), len(lines))
    return {"path": path, "content": "".join(lines[start_line - 1:last]), "start_line": start_line,
        "end_line": last, "total_lines": len(lines), "writable": files.can_write(path)}


def edit_file(files, path, operation, new_content, old_content=""):
    """Stage a create, unique exact replacement, prepend or append in the current batch."""
    files.path(path)  # Reject unsafe paths before attempting task-specific adaptation.
    requested = path
    if operation == "create" and files.pending_target and files._target_path is None:
        path = files.target.adapt(path)
        files.path(path)
        files._target_path = path
    if not files.can_write(path) and path != files._target_path:
        raise FileToolError("WRITE_NOT_ALLOWED", "File is not writable for this task", path)
    if not isinstance(new_content, str) or not isinstance(old_content, str):
        raise FileToolError("INVALID_ARGUMENTS", "old_content and new_content must be strings", path)
    new_content, old_content = normalize_newlines(new_content), normalize_newlines(old_content)
    target = files.path(path)
    current = files._pending.get(path, read_source(target) if target.is_file() else None)
    if operation == "create":
        if current is not None:
            raise FileToolError("FILE_ALREADY_EXISTS", "Read the existing file and use replace", path)
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
    result = {"path": path, "operation": operation}
    if path != requested:
        result["requested_path"] = requested
        result["notice"] = "Adapted to this task's required destination; use path in future calls and imports"
    return result

