"""Shared file-tool execution and public interfaces for compiler agents."""

from copy import deepcopy
from pathlib import Path

from infrastructure.shared.agent.targets import FileTarget
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.utils.files import read_source, save_bytes, save_text

from .files import FileToolError, edit_file, read_file, workspace_path
from .schemas import TOOL_REGISTRY, definition


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
        for call in calls:
            name = call["tool"]
            if name not in TOOL_REGISTRY:
                raise FileToolError("UNKNOWN_TOOL", f"Unknown tool: {name}")
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
            for call in calls:
                name, arguments = call["tool"], call["arguments"]
                if name not in TOOL_REGISTRY:
                    raise FileToolError("UNKNOWN_TOOL", f"Unknown tool: {name}")
                function, schema, _effect = TOOL_REGISTRY[name]
                parameters = schema["function"]["parameters"]
                if not isinstance(arguments, dict) or set(arguments) - set(parameters["properties"]) or any(
                        key not in arguments for key in parameters["required"]):
                    raise FileToolError("INVALID_ARGUMENTS", f"Use the declared parameters of {name}")
                results.append({"tool": name, "result": function(self, **arguments)})
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
