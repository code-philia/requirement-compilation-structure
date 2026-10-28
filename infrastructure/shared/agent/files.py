"""Shared edit-batch execution; this module does not decide what to implement.

The stage supplies writable roots, context paths, and check callbacks. The agent
sees refreshed source through state(), submits exact text edits through edit_files(),
and records requirement/module ownership through FileIndex after successful writes."""

from pathlib import Path
import re

from infrastructure.utils.files import save_text

EXCLUDED = {"node_modules", ".git", ".arc", "dist", "build", "coverage", "__pycache__", ".venv"}


def project_structure(output: Path, root: str = "backend", depth: int = 3, limit: int = 180) -> str:
    """Show only a shallow source tree; never descend into generated/dependency trees."""
    lines = [root + "/"]

    def visit(directory, level):
        """Append visible source entries recursively, stopping at the depth and entry limits."""
        if level > depth or len(lines) >= limit:
            return
        for path in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name)):
            if path.name.startswith(".") or path.name in EXCLUDED or path.is_symlink() or path == output / "backend/data":
                continue
            if len(lines) >= limit:
                break
            lines.append("  " * level + path.name + ("/" if path.is_dir() else ""))
            if path.is_dir():
                visit(path, level + 1)

    target = output / root
    if target.is_dir():
        visit(target, 1)
    if len(lines) >= limit:
        lines.append("... (entry limit reached)")
    return "\n".join(lines)


class FileTools:
    """Compiler-controlled file context and edit tools shared by backend, UI, and event agents."""
    def __init__(self, output: Path, editable: set[str] | None, checks, *, roots=(), read_roots=None, context_files=(), protected=(), index=None, requirements=(), module=None, entrypoint_modules=()) -> None:
        """Configure the compiler-selected context, writable scope, checks, and file index.

        An explicit editable set restricts test generation to known files. Source
        roots let implementation agents choose paths while protecting compiler files."""
        self.output = output.resolve()
        self.editable = editable
        self.checks = checks
        self.roots = tuple(roots)
        self.read_roots = tuple(read_roots) if read_roots is not None else self.roots
        self.context_files = set(context_files)
        self.protected = tuple(protected)
        self.index, self.requirements, self.module = index, tuple(requirements), module
        self.entrypoint_modules = set(entrypoint_modules)
        self.observed = {}
        if editable is None and not roots:
            raise ValueError("Provide editable files or source roots")
        if index is not None and not module:
            raise ValueError("A module ID is required for file traceability")

    def path(self, relative: str, writing: bool = True) -> Path:
        """Resolve a workspace-relative path and reject traversal, excluded trees, or disallowed access."""
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts or "\\" in relative:
            raise ValueError("Use a workspace-relative path without parent traversal")
        parts = Path(relative).parts
        if any(part in EXCLUDED or part.startswith(".") for part in parts):
            raise ValueError("Dependency, hidden, and generated paths are excluded")
        if parts[:2] == ("backend", "data"):
            raise ValueError("Runtime database files are excluded")
        target = (self.output / relative).resolve()
        if not target.is_relative_to(self.output) or target.relative_to(self.output).as_posix() != relative:
            raise ValueError("Use a canonical workspace-relative path without symlinks")
        if writing:
            if self.editable is not None and relative not in self.editable:
                raise ValueError(f"Editable files: {sorted(self.editable)}")
            if self.editable is None and not any(target.is_relative_to(self.output / root) for root in self.roots):
                raise ValueError(f"Editable source roots: {self.roots}")
            if any(target == self.output / path or target.is_relative_to(self.output / path) for path in self.protected):
                raise ValueError(f"Compiler-owned file or directory: {relative}")
            if target.suffix not in {".ts", ".tsx", ".js", ".jsx", ".css", ".json", ".html", ".sql", ".md"}:
                raise ValueError("Edit only text source files")
        elif relative in self.context_files:
            pass
        elif self.editable is not None:
            if relative not in self.editable:
                raise ValueError("File is outside the compiler-selected context")
        elif not any(target.is_relative_to(self.output / root) for root in self.read_roots):
            raise ValueError(f"Readable source roots: {self.read_roots}")
        return target

    def provide_files(self, paths) -> None:
        """Called by the compiler, never exposed as a model tool."""
        self.context_files.update(paths)
        for relative in self.context_files:
            self.path(relative, writing=False)

    def state(self) -> dict:
        """Refresh supplied file contents and expose the current writable scope and entrypoints to the model."""
        related = self.index.files_for(self.requirements, self.module) if self.index else []
        selected = set(self.context_files) | set(self.editable or ()) | set(self.observed)
        for relative in related:
            try:
                self.path(relative, writing=False)
            except ValueError:
                continue
            selected.add(relative)
        for relative in sorted(selected):
            target = self.path(relative, writing=False)
            self.observed[relative] = target.read_bytes().decode("utf-8") if target.is_file() else None
        return {
            "editable_files": sorted(self.editable) if self.editable is not None else None,
            "source_roots": self.roots, "context_roots": self.read_roots, "protected_paths": self.protected,
            "files": dict(self.observed),
            "related_files": sorted(set(related) & selected),
            "module_entrypoint": self.index.data["entrypoints"].get(self.module) if self.index else None,
            "entrypoint_modules": sorted(self.entrypoint_modules),
            "selected_entrypoints": {key: self.index.data["entrypoints"].get(key) for key in sorted(self.entrypoint_modules)} if self.index else {},
            "project_structure": {root: project_structure(self.output, root) for root in sorted({root.split('/')[0] for root in self.roots})},
        }

    def edit_files(self, arguments: dict) -> dict:
        """Validate and apply an exact edit batch, then publish its file associations.

        Existing text must match the compiler-supplied version. Validate all edits
        before writing; restore original contents if writing or index publication fails."""
        if set(arguments) - {"edits", "entrypoint", "entrypoints"} or not isinstance(arguments.get("edits"), list) or not arguments["edits"]:
            raise ValueError("Provide a nonempty edits list and optional module entrypoint")
        # Stage changes in memory so a malformed later edit cannot partially apply.
        staged, originals = {}, {}
        for edit in arguments["edits"]:
            if not isinstance(edit, dict) or set(edit) != {"path", "operation", "old_content", "new_content"} or any(not isinstance(value, str) for value in edit.values()):
                raise ValueError("Each edit needs string path, operation, old_content, new_content")
            relative, operation = edit["path"], edit["operation"]
            target = self.path(relative)
            if relative not in staged:
                originals[relative] = target.read_bytes().decode("utf-8") if target.is_file() else None
                staged[relative] = originals[relative]
            content = staged[relative]
            old, new = edit["old_content"], edit["new_content"]
            if operation == "create":
                if content is not None or old:
                    raise ValueError("create requires a nonexistent file and empty old_content")
                content = new
            else:
                if content is None:
                    raise ValueError(f"{operation} requires an existing file: {relative}")
                if originals[relative] is not None:
                    if self.observed.get(relative) is None:
                        raise ValueError(f"Existing file content was not supplied by the compiler: {relative}; edit supplied files or create a new module")
                    if self.observed[relative] != originals[relative]:
                        raise ValueError(f"File changed after context was supplied: {relative}; retry with the next refreshed context")
                if operation == "replace":
                    if not old or content.count(old) != 1:
                        raise ValueError(f"replace needs nonempty old_content matching exactly once: {relative}")
                    content = content.replace(old, new, 1)
                elif operation in {"prepend", "append"}:
                    if old:
                        raise ValueError(f"{operation} requires empty old_content")
                    content = new + content if operation == "prepend" else content + new
                else:
                    raise ValueError(f"Unknown edit operation: {operation}")
            staged[relative] = content
        # Entrypoints connect semantic modules to the model's chosen source files.
        entry = arguments.get("entrypoint")
        entries = arguments.get("entrypoints", {})
        if not isinstance(entries, dict) or set(entries) - self.entrypoint_modules or (entry is not None and (entries or self.entrypoint_modules)):
            raise ValueError("Choose either entrypoint or an entrypoints object limited to the supplied module IDs")
        for entry in [*entries.values(), *([entry] if entry is not None else [])]:
            if self.editable is not None or not self.index or not isinstance(entry, dict) or set(entry) != {"path", "export"} or not isinstance(entry["export"], str) or not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", entry["export"]):
                raise ValueError("entrypoint requires a tracked module, path, and named export")
            target = self.path(entry["path"])
            if entry["path"] not in staged and entry["path"] not in self.observed:
                raise ValueError("Choose an entrypoint from supplied files or this edit batch")
            if target.suffix not in {".ts", ".tsx"} or (entry["path"] not in staged and not target.is_file()):
                raise ValueError("The entrypoint must be an existing or newly created TypeScript/TSX source file")
        # Validate the complete batch before writing; roll back filesystem errors.
        written = []
        try:
            for relative, content in staged.items():
                save_text(self.path(relative), content)
                written.append(relative)
            if self.index:
                self.index.record(staged, self.requirements, self.module, arguments.get("entrypoint"), entrypoints=entries)
        except (OSError, ValueError):
            for relative in reversed(written):
                target = self.path(relative)
                if originals[relative] is None:
                    target.unlink(missing_ok=True)
                else:
                    save_text(target, originals[relative])
            raise
        self.observed.update(staged)
        return {"paths": list(staged), "edits": len(arguments["edits"]), "entrypoint": arguments.get("entrypoint"), "entrypoints": entries}

    def dispatch(self, tool: str, arguments: dict):
        """Execute one supported tool action; the model cannot read arbitrary files or run shell commands."""
        if tool == "run_checks" and arguments == {}:
            return self.checks()
        if tool == "edit_files":
            return self.edit_files(arguments)
        if tool == "finish" and arguments == {}:
            return {"requested": "finish"}
        raise ValueError("Unknown tool or invalid arguments")
