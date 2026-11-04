"""Shared file-tool execution and public interfaces for compiler agents."""

from copy import deepcopy
from pathlib import Path

from infrastructure.shared.agent.context import FILE_LINKS, project_files, related_files, record_files
from infrastructure.shared.agent.files import editable_application_path, source_paths
from infrastructure.utils.files import read_source, save_bytes, save_text

from .files import FileToolError, workspace_path
from .schemas import TOOL_REGISTRY


class FileTools:
    """One scoped read/write workspace with automatic requirement-file associations."""

    def __init__(self, output, scope, *, requirements=(), stage, files=(), writable=None,
            readable=None, allow_write=None):
        self.output = Path(output).resolve()
        self.scope = tuple(scope)
        if not self.scope:
            raise ValueError("Implementation requires at least one project scope")
        for directory in self.scope:
            if not directory or Path(directory).is_absolute() or ".." in Path(directory).parts or directory.startswith("."):
                raise ValueError(f"Invalid project scope: {directory}")
        self.requirements = list(dict.fromkeys(requirements))
        self.stage = stage
        self.related_files = set(files) | related_files(self.output, self.requirements)
        self.files = self.related_files | project_files(self.output, self.scope)
        self.writable = set(writable) if writable is not None else None
        self.allow_write = allow_write
        self.readable = set(readable) if readable is not None else None
        if self.readable is not None:
            self.files.intersection_update(self.readable)
        self.changed_paths, self.last_changes = set(), []
        self.available_paths = set(self.files)
        for directory in self.scope:
            self.available_paths.update(source_paths(self.output, directory))
        self.available_paths = {path for path in self.available_paths if self.can_read(path)}
        self.supplied_contents, self.read_files, self._pending = {}, {}, {}
        for path in self.files:
            self.path(path)

    def path(self, path):
        return workspace_path(self.output, path)

    def in_scope(self, path):
        return any(path == directory or path.startswith(directory.rstrip("/") + "/") for directory in self.scope)

    def can_read(self, path):
        if self.readable is not None:
            return path in self.readable
        return self.in_scope(path) or path in self.files

    def can_write(self, path):
        if not self.in_scope(path):
            return False
        if self.writable is not None:
            return path in self.writable
        if self.allow_write is not None:
            return self.allow_write(path)
        return editable_application_path(self.output, path)

    def scope_state(self):
        return {"directories": list(self.scope), "existing_files": sorted(self.available_paths),
            "writable_files": sorted(self.writable) if self.writable is not None else "application sources inside scope",
            "requirement_ids": self.requirements,
            "readable_files": sorted(self.readable) if self.readable is not None else "scope and related reference files",
            "related_files": sorted(path for path in self.related_files if self.can_read(path))}

    def state(self):
        """Supply complete current readable contents, so related files need no extra read call."""
        records = {}
        self.supplied_contents = {}
        for path in sorted(self.files):
            target = self.path(path)
            readable = self.can_read(path)
            content = read_source(target) if target.is_file() and readable else None
            records[path] = {"content": content, "readable": readable,
                "writable": self.can_write(path), "exists": target.is_file()}
            if content is not None:
                self.supplied_contents[path] = content
        return records

    def schemas(self):
        return deepcopy([item[1] for item in TOOL_REGISTRY.values()])

    def effect(self, calls):
        """Classify a batch before execution; read arguments are validated per item."""
        if not isinstance(calls, list):
            raise FileToolError("INVALID_CALLS", "tool_calls must be an array")
        effects = set()
        for number, call in enumerate(calls, 1):
            if not isinstance(call, dict) or not isinstance(call.get("tool"), str):
                raise FileToolError("INVALID_CALL", "Each tool_calls item must be an object with a tool name", call_index=number)
            name = call["tool"]
            if name not in TOOL_REGISTRY:
                raise FileToolError("UNKNOWN_TOOL", f"Unknown tool {name!r}",
                    call_index=number, available_tools=list(TOOL_REGISTRY))
            effects.add(TOOL_REGISTRY[name][2])
        if len(effects) > 1:
            raise FileToolError("MIXED_TOOL_BATCH", "Separate read calls from edit calls; inspect reads before editing")
        return next(iter(effects), "write")

    def validate_call(self, call, number):
        schema = TOOL_REGISTRY[call["tool"]][1]
        parameters = schema["parameters"]
        missing = [key for key in parameters["required"] if key not in call]
        unexpected = sorted(set(call) - set(parameters["properties"]))
        invalid = []
        for key, rule in parameters["properties"].items():
            if key not in call:
                continue
            value = call[key]
            if rule["type"] == "string" and not isinstance(value, str):
                invalid.append(f"{key} must be a string")
            elif rule["type"] == "integer" and type(value) is not int:
                invalid.append(f"{key} must be an integer")
            elif "minimum" in rule and value < rule["minimum"]:
                invalid.append(f"{key} must be >= {rule['minimum']}")
            elif "enum" in rule and value not in rule["enum"]:
                invalid.append(f"{key} must be one of {rule['enum']}")
        if missing or unexpected or invalid:
            raise FileToolError("INVALID_CALL", f"Invalid {call['tool']} call at item {number}. Put parameters beside tool, without an arguments wrapper.",
                call_index=number, tool=call["tool"], missing_fields=missing,
                unexpected_fields=unexpected, invalid_fields=invalid, example=schema["example"])

    def execute(self, calls):
        """Keep read results independent; publish writes and requirement links atomically."""
        effect = self.effect(calls)
        self._pending, self.last_changes = {}, []
        results, originals, written = [], {}, []
        index_path = self.output / ".arc" / FILE_LINKS
        index_before = index_path.read_bytes() if effect == "write" and index_path.is_file() else None
        index_changed = False
        try:
            for number, call in enumerate(calls, 1):
                name = call["tool"]
                function, schema, _effect = TOOL_REGISTRY[name]
                parameters = {key: value for key, value in call.items() if key != "tool"}
                try:
                    self.validate_call(call, number)
                    result = function(self, **parameters)
                except FileToolError as error:
                    error.feedback.update(call_index=number, tool=name, example=schema["example"])
                    if effect == "read":
                        results.append({"tool": name, "error": error.feedback})
                        continue
                    raise
                except (ValueError, TypeError, OSError) as error:
                    failure = FileToolError("FILE_TOOL_FAILED", str(error), call.get("path"),
                        call_index=number, tool=name, example=schema["example"])
                    if effect == "read":
                        results.append({"tool": name, "error": failure.feedback})
                        continue
                    raise failure from error
                results.append({"tool": name, "result": result})
            if effect == "read":
                return results
            for path, content in self._pending.items():
                target = self.path(path)
                originals[path] = target.read_bytes() if target.is_file() else None
                self.last_changes.append({"path": path,
                    "before": read_source(target) if target.is_file() else None, "after": content})
            for path, content in self._pending.items():
                save_text(self.path(path), content)
                written.append(path)
            known = {path for path in self.related_files if self.can_write(path) and self.path(path).is_file()} | set(self._pending)
            if self.requirements and known:
                index_changed = True
                record_files(self.output, self.requirements, self.stage, known)
            self.related_files.update(self._pending)
            self.files.update(self._pending)
            self.available_paths.update(self._pending)
            self.changed_paths.update(self._pending)
            return results
        except Exception:
            for path in reversed(written):
                target = self.path(path)
                if originals[path] is None:
                    target.unlink(missing_ok=True)
                else:
                    save_bytes(target, originals[path])
            if index_changed:
                if index_before is None:
                    index_path.unlink(missing_ok=True)
                else:
                    save_bytes(index_path, index_before)
            self.last_changes = []
            raise
        finally:
            self._pending = {}
