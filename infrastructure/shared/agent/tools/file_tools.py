"""Scoped file operations and definitions for native function tool calls."""

from copy import deepcopy
import json
from pathlib import Path

from infrastructure.shared.agent.context import FILE_LINKS, record_files
from infrastructure.shared.agent.files import EXCLUDED
from infrastructure.utils.files import normalize_newlines, read_source, save_bytes, save_text
from infrastructure.utils.paths import check_path_case, relative_path


NATIVE_FILE_TOOLS = {
    "read_file": {"type": "function", "function": {
        "name": "read_file", "description": "Read a permitted file or an inclusive 1-based line range.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1}},
            "required": ["path"], "additionalProperties": False}}},
    "edit_file": {"type": "function", "function": {
        "name": "edit_file",
        "description": "Create a missing file, replace one unique exact text span, or append/prepend text. "
            "Use only permitted project-relative paths. Preserve unrelated contents; whole-file replacement is forbidden.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "operation": {"type": "string", "enum": ["create", "replace", "append", "prepend"]},
            "new_content": {"type": "string"}, "old_content": {"type": "string"}},
            "required": ["path", "operation", "new_content"], "additionalProperties": False}}},
    "search_files": {"type": "function", "function": {
        "name": "search_files", "description": "Find literal text in permitted source files, returning paths and line numbers.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 200}},
            "required": ["query"], "additionalProperties": False}}},
}


class NativeFileTools:
    """Execute SDK tool calls directly with explicit file permissions and batch rollback."""

    def __init__(self, output: Path, *, readable, writable, requirements=(), stage: str):
        self.output = Path(output).resolve()
        self.writable = set(writable)
        self.readable = set(readable) | self.writable
        self.requirements = list(requirements)
        self.stage = stage
        self.changed_paths = set()
        for path in self.readable:
            self.resolve_path(path)

    def resolve_path(self, path: str) -> Path:
        parts = relative_path(path).parts
        if any(part.startswith(".") or part in EXCLUDED for part in parts) or parts[:2] == ("backend", "data"):
            raise ValueError(f"Use a project source/configuration path: {path}")
        check_path_case(self.output, path)
        target = self.output
        for part in parts:
            target = target / part
            if target.is_symlink():
                raise ValueError(f"Symbolic links are not permitted: {path}")
        if not target.resolve().is_relative_to(self.output) or target.is_dir():
            raise ValueError(f"Expected a project-relative file path: {path}")
        return target

    def definitions(self, names) -> list[dict]:
        return [deepcopy(NATIVE_FILE_TOOLS[name]) for name in names]

    def describe(self) -> dict:
        directories = set()
        existing = []
        for path in sorted(self.readable):
            directories.add(Path(path).parent.as_posix())
            if self.resolve_path(path).is_file():
                existing.append(path)
        return {"directories": sorted(directories), "existing_files": existing,
            "writable_files": sorted(self.writable)}

    def snapshot(self) -> dict:
        records = {}
        for path in sorted(self.readable):
            target = self.resolve_path(path)
            exists = target.is_file()
            records[path] = {"exists": exists, "writable": path in self.writable,
                "content": read_source(target) if exists else None}
        return records

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> dict:
        if path not in self.readable:
            raise ValueError(f"File is not readable: {path}")
        if type(start_line) is not int or start_line < 1:
            raise ValueError("start_line must be a positive integer")
        if end_line is not None and (type(end_line) is not int or end_line < start_line):
            raise ValueError("end_line must be an integer at or after start_line")
        target = self.resolve_path(path)
        if not target.is_file():
            raise ValueError(f"File does not exist: {path}")
        lines = read_source(target).splitlines(keepends=True)
        last = len(lines) if end_line is None else min(end_line, len(lines))
        return {"path": path, "content": "".join(lines[start_line - 1:last]),
            "start_line": start_line, "end_line": last, "total_lines": len(lines)}

    def search_files(self, query: str, max_results: int = 50) -> dict:
        if not isinstance(query, str) or not query:
            raise ValueError("query must be nonempty literal text")
        if type(max_results) is not int or not 1 <= max_results <= 200:
            raise ValueError("max_results must be between 1 and 200")
        matches = []
        for path in sorted(self.readable):
            target = self.resolve_path(path)
            if not target.is_file():
                continue
            for number, line in enumerate(read_source(target).splitlines(), 1):
                if query not in line:
                    continue
                if len(matches) == max_results:
                    return {"matches": matches, "truncated": True}
                matches.append({"path": path, "line": number, "content": line})
        return {"matches": matches, "truncated": False}

    def edit_file(self, path: str, operation: str, new_content: str, old_content: str = "", *, pending: dict) -> dict:
        """Prepare an edit; execute() publishes the entire batch after validation."""
        if path not in self.writable:
            raise ValueError(f"File is not writable: {path}")
        if not isinstance(new_content, str) or not isinstance(old_content, str):
            raise ValueError("new_content and old_content must be strings")
        target = self.resolve_path(path)
        current = pending.get(path)
        if path not in pending:
            current = read_source(target) if target.is_file() else None
        new_content = normalize_newlines(new_content)
        old_content = normalize_newlines(old_content)
        if operation == "create":
            if current is not None:
                raise ValueError(f"File already exists: {path}")
            if old_content:
                raise ValueError("create requires empty old_content")
            updated = new_content
        elif operation in {"replace", "append", "prepend"}:
            if current is None:
                raise ValueError(f"File does not exist; use create: {path}")
            if operation == "replace":
                if not old_content or current.count(old_content) != 1:
                    raise ValueError("replace requires one unique exact old_content match")
                if current.strip() and current.strip() == old_content.strip():
                    raise ValueError("Replace a local span, not the entire existing file")
                updated = current.replace(old_content, new_content, 1)
            else:
                if old_content:
                    raise ValueError("append/prepend require empty old_content")
                updated = current + new_content if operation == "append" else new_content + current
        else:
            raise ValueError("operation must be create, replace, append or prepend")
        pending[path] = updated
        return {"path": path, "operation": operation}

    def execute(self, tool_calls) -> list[dict]:
        """Accept native SDK calls and return matching role=tool messages."""
        pending = {}
        messages = []
        names = {call.function.name for call in tool_calls}
        if "edit_file" in names and names != {"edit_file"}:
            raise ValueError("Separate editing from reading/searching in different responses")
        for call in tool_calls:
            name = call.function.name
            if name not in NATIVE_FILE_TOOLS:
                raise ValueError(f"Unknown file tool: {name}")
            arguments = json.loads(call.function.arguments)
            schema = NATIVE_FILE_TOOLS[name]["function"]["parameters"]
            if not isinstance(arguments, dict):
                raise ValueError("Native tool arguments must be an object")
            if set(arguments) - set(schema["properties"]) or set(schema["required"]) - set(arguments):
                raise ValueError(f"Invalid arguments for {name}")
            for parameter, value in arguments.items():
                rule = schema["properties"][parameter]
                if rule["type"] == "string" and not isinstance(value, str):
                    raise ValueError(f"{parameter} must be a string")
                if rule["type"] == "integer" and type(value) is not int:
                    raise ValueError(f"{parameter} must be an integer")
                if "enum" in rule and value not in rule["enum"]:
                    raise ValueError(f"Invalid {parameter}: {value}")
            if name == "edit_file":
                result = self.edit_file(**arguments, pending=pending)
            elif name == "read_file":
                result = self.read_file(**arguments)
            else:
                result = self.search_files(**arguments)
            messages.append({"role": "tool", "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False)})
        originals = {}
        written = []
        index = self.output / ".arc" / FILE_LINKS
        index_before = index.read_bytes() if pending and index.is_file() else None
        recording = False
        try:
            for path, content in pending.items():
                target = self.resolve_path(path)
                originals[path] = target.read_bytes() if target.is_file() else None
                written.append(path)
                save_text(target, content)
            if pending and self.requirements:
                recording = True
                record_files(self.output, self.requirements, self.stage, pending)
        except Exception:
            for path in reversed(written):
                target = self.resolve_path(path)
                if originals[path] is None:
                    target.unlink(missing_ok=True)
                else:
                    save_bytes(target, originals[path])
            if recording:
                if index_before is None:
                    index.unlink(missing_ok=True)
                else:
                    save_bytes(index, index_before)
            raise
        self.changed_paths.update(pending)
        return messages
