"""Shared file-tool execution and public interfaces for compiler agents."""

from copy import deepcopy
from pathlib import Path

from infrastructure.shared.agent.targets import FileTarget
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.utils.files import read_source, save_bytes, save_text

from .files import FileToolError, edit_file, read_file, workspace_path
from .schemas import TOOL_REGISTRY


class FileTools:
    """Pin useful task files and dispatch shared tools; no full-file observation/version map."""

    def __init__(self, output, writable=(), references=(), *, target=None, allow_write=None, readable=None):
        self.output = Path(output).resolve()
        self.writable, self.files = set(writable), set(writable) | set(references)
        self.target, self.allow_write = target, allow_write
        self.readable = set(readable) if readable is not None else None
        self.changed_paths, self.last_changes = set(), []
        self._pending, self._target_path = {}, None
        for path in self.files:
            self.path(path)

    @classmethod
    def for_target(cls, output, kind, identity, references=(), writable=(), existing=None, fixed_path=None, **kwargs):
        output = Path(output).resolve()
        target = FileTarget.load(output, kind, identity, existing, fixed_path)
        paths = set(writable) | ({target.path} if target.path else set())
        return cls(output, paths, references, target=target, **kwargs)

    def path(self, path):
        return workspace_path(self.output, path)

    @property
    def pending_target(self):
        return self.target is not None and (self.target.path is None or not self.path(self.target.path).is_file())

    def can_write(self, path):
        return path in self.writable or bool(self.allow_write and self.allow_write(path))

    def state(self):
        return {path: {"content": read_source(self.path(path)) if self.path(path).is_file() else None,
            "writable": self.can_write(path)} for path in sorted(self.files)}

    def task_state(self, task):
        task = {**task}
        if self.target:
            task["file_target"] = self.target.context()
            if self.target.path:
                key = "test_path" if self.target.kind.endswith("test") else "implementation_path"
                task[key] = self.target.path
        for key, kind in (("implementation_paths", "trigger"), ("page_paths", "page")):
            if isinstance(task.get(key), dict):
                task[key] = {identity: selected_path(self.output, kind, identity) or path
                    for identity, path in task[key].items()}
        return task

    def schemas(self):
        return deepcopy([item[1] for item in TOOL_REGISTRY.values()])

    def effect(self, calls):
        """Registered effects determine whether to continue reading or run acceptance."""
        if not isinstance(calls, list):
            raise FileToolError("INVALID_CALLS", "tool_calls must be an array")
        effects = set()
        for number, call in enumerate(calls, 1):
            if not isinstance(call, dict) or not isinstance(call.get("tool"), str):
                raise FileToolError("INVALID_CALL", "Each tool_calls item must be an object with a tool name",
                    call_index=number, examples=[item[1]["example"] for item in TOOL_REGISTRY.values()])
            name = call["tool"]
            if name not in TOOL_REGISTRY:
                raise FileToolError("UNKNOWN_TOOL", f"Unknown tool {name!r}; use read_file or edit_file",
                    call_index=number, tool=name, available_tools=list(TOOL_REGISTRY))
            schema = TOOL_REGISTRY[name][1]
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
                raise FileToolError("INVALID_CALL", f"Invalid {name} call at tool_calls item {number}. "
                    "Put path and other parameters beside tool, without an arguments wrapper.",
                    call_index=number, tool=name, missing_fields=missing, unexpected_fields=unexpected,
                    invalid_fields=invalid, example=schema["example"])
            effects.add(TOOL_REGISTRY[name][2])
        if len(effects) > 1:
            raise FileToolError("MIXED_TOOL_BATCH", "Separate read calls from edit calls; inspect reads before editing")
        return next(iter(effects), "write")

    def execute(self, calls):
        """Validate/stage a complete edit batch, then publish or restore every affected file."""
        self.effect(calls)
        self._pending, self._target_path, self.last_changes = {}, None, []
        results, originals, written = [], {}, []
        index_path = self.output / ".arc/implementation_paths.json"
        index_before = index_path.read_bytes() if index_path.is_file() else None
        try:
            for number, call in enumerate(calls, 1):
                name = call["tool"]
                function, schema, _effect = TOOL_REGISTRY[name]
                parameters = {key: value for key, value in call.items() if key != "tool"}
                try:
                    result = function(self, **parameters)
                except FileToolError as error:
                    error.feedback.update(call_index=number, tool=name, example=schema["example"])
                    raise
                except (ValueError, TypeError, OSError) as error:
                    raise FileToolError("FILE_TOOL_FAILED", str(error), call.get("path"),
                        call_index=number, tool=name, example=schema["example"]) from error
                results.append({"tool": name, "result": result})
            for path, content in self._pending.items():
                target = self.path(path)
                originals[path] = target.read_bytes() if target.is_file() else None
                self.last_changes.append({"path": path,
                    "before": read_source(target) if target.is_file() else None, "after": content})
            for path, content in self._pending.items():
                save_text(self.path(path), content)
                written.append(path)
            if self._target_path is not None:
                self.target.bind(self.output, self._target_path)
                self.files.add(self._target_path)
                self.writable.add(self._target_path)
            self.changed_paths.update(self._pending)
            return results
        except Exception:
            for path in reversed(written):
                target = self.path(path)
                if originals[path] is None:
                    target.unlink(missing_ok=True)
                else:
                    save_bytes(target, originals[path])
            if written and self._target_path is not None:
                if index_before is None:
                    index_path.unlink(missing_ok=True)
                else:
                    save_bytes(index_path, index_before)
            self.last_changes = []
            raise
        finally:
            self._pending, self._target_path = {}, None
