"""Scoped whole-file edits with model-selected paths for new target files."""

from pathlib import Path

from infrastructure.utils.files import read_source, save_bytes, save_text
from infrastructure.utils.paths import check_path_case, relative_path
from infrastructure.shared.project.entrypoints import FILE_ROOTS, remember_path, selected_path

EXCLUDED = {"node_modules", ".git", ".arc", "dist", "build", "coverage", "__pycache__", ".venv"}


def source_paths(output: Path, root: str) -> list[str]:
    """Supply text sources from a fixed project directory without a file association index."""
    return sorted(path.relative_to(output).as_posix() for path in (output / root).rglob("*")
        if path.is_file() and not path.is_symlink()
        and not any(part.startswith(".") or part in EXCLUDED for part in path.relative_to(output).parts)
        and path.suffix in {".ts", ".tsx", ".js", ".jsx", ".css", ".json", ".html", ".sql", ".md"})


def editable_sources(output: Path, root: str) -> list[str]:
    """Allow source repairs across the layer while retaining compiler-owned wiring."""
    templates = Path(__file__).resolve().parents[1] / "project/templates"
    generated = {"backend/src/api/register.ts", "frontend/src/ui-runtime.ts",
        "frontend/src/ui-api.ts", "frontend/src/ui-triggers.ts"}
    return [relative for relative in source_paths(output, root)
        if relative not in generated and not (templates / relative).is_file()
        and not relative.startswith("backend/src/db/")]


class FileWorkspace:
    """Expose a single file map and accept edits only to explicitly writable paths."""

    def __init__(self, output: Path, writable, references=(), new_file=None):
        self.output = output.resolve()
        self.writable = set(writable)
        self.files = self.writable | set(references)
        self.observed = {}
        self.new_file = new_file
        self.target = new_file
        for path in self.files:
            self.path(path)

    @classmethod
    def for_target(cls, output: Path, kind: str, identity: str, references=(), writable=(), existing=None):
        """Let the model select a new target's path; retain an existing target's path."""
        relative = selected_path(output, kind, identity) or existing
        if relative and (output / relative).is_file():
            workspace = cls(output, {*writable, relative}, references)
            workspace.target = (kind, identity)
            return workspace
        return cls(output, writable, references, new_file=(kind, identity))

    def task_state(self, task: dict) -> dict:
        """Refresh path hints after creation without changing earlier request snapshots."""
        result = {**task}
        result.pop("new_file", None)
        if self.target is not None:
            kind, identity = self.target
            relative = selected_path(self.output, kind, identity)
            if relative is not None and kind in {"api", "page", "backend_test", "e2e_test"}:
                key = "test_path" if kind in {"backend_test", "e2e_test"} else "implementation_path"
                result[key] = relative
        for key, kind in (("implementation_paths", "trigger"), ("page_paths", "page")):
            if isinstance(task.get(key), dict):
                result[key] = {identity: selected_path(self.output, kind, identity) or relative
                    for identity, relative in task[key].items()}
        return {**result, **self.creation_task()}

    def creation_task(self) -> dict:
        """Explain the creation destination without prescribing a filename."""
        if self.new_file is None:
            return {}
        kind, identity = self.new_file
        return {"new_file": {"target": identity, "kind": kind, "directory": FILE_ROOTS[kind],
            "instructions": "Choose the path. The first edit creates this target's file. Subsequent edits may update supplied writable files."}}

    def path(self, relative: str) -> Path:
        """Reject traversal, symlinks, case aliases and noncanonical source paths."""
        parts = relative_path(relative).parts
        check_path_case(self.output, relative)
        if any(part.startswith(".") or part in EXCLUDED for part in parts) or parts[:2] == ("backend", "data"):
            raise ValueError(f"Not a source file: {relative}")
        target = self.output / relative
        current = self.output
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"Symlinks are not allowed: {relative}")
        if not target.resolve().is_relative_to(self.output) or target.is_dir():
            raise ValueError(f"Not a workspace source file: {relative}")
        return target

    def state(self) -> dict:
        """Refresh all supplied contents before each model request."""
        self.observed = {path: read_source(self.path(path)) if self.path(path).is_file() else None
            for path in sorted(self.files)}
        return {path: {"content": content, "writable": path in self.writable}
            for path, content in self.observed.items()}

    def apply(self, response: dict) -> None:
        """Validate the complete batch before writing; restore original bytes on write failure."""
        staged, originals = {}, {}
        created = None
        for number, edit in enumerate(response["edits"]):
            relative = edit["path"]
            target = self.path(relative)
            if relative == created:
                staged[relative] = edit["content"]
                continue
            if self.new_file is not None and number == 0:
                kind, identity = self.new_file
                root = FILE_ROOTS[kind]
                if not relative.startswith(root + "/") or target.exists() or relative in self.files:
                    raise ValueError(f"Choose an unused path under {root} for {identity}")
                created = relative
                originals[relative] = None
                staged[relative] = edit["content"]
                continue
            if relative not in self.writable:
                raise ValueError(f"File is not writable: {relative}")
            if relative not in self.observed:
                raise ValueError(f"File was not supplied: {relative}")
            if (read_source(target) if target.is_file() else None) != self.observed[relative]:
                raise ValueError(f"File changed since it was supplied: {relative}")
            originals[relative] = target.read_bytes() if target.is_file() else None
            staged[relative] = edit["content"]
        written = []
        try:
            for relative, content in staged.items():
                save_text(self.path(relative), content)
                written.append(relative)
            if created is not None:
                remember_path(self.output, *self.new_file, created)
        except (OSError, ValueError):
            for relative in reversed(written):
                if originals[relative] is None:
                    self.path(relative).unlink(missing_ok=True)
                else:
                    save_bytes(self.path(relative), originals[relative])
            raise
        if created is not None:
            self.writable.add(created)
            self.files.add(created)
            self.new_file = None
