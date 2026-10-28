"""Compiler-selected files with one writable flag and whole-file edit batches."""

from pathlib import Path

from infrastructure.utils.files import read_source, save_bytes, save_text
from infrastructure.utils.paths import check_path_case, relative_path

EXCLUDED = {"node_modules", ".git", ".arc", "dist", "build", "coverage", "__pycache__", ".venv"}


def source_paths(output: Path, root: str) -> list[str]:
    """Supply text sources from a fixed project directory without a file association index."""
    return sorted(path.relative_to(output).as_posix() for path in (output / root).rglob("*")
        if path.is_file() and not path.is_symlink()
        and not any(part.startswith(".") or part in EXCLUDED for part in path.relative_to(output).parts)
        and path.suffix in {".ts", ".tsx", ".js", ".jsx", ".css", ".json", ".html", ".sql", ".md"})


class FileWorkspace:
    """Expose a single file map and accept edits only to explicitly writable paths."""

    def __init__(self, output: Path, writable, references=()):
        self.output = output.resolve()
        self.writable = set(writable)
        self.files = self.writable | set(references)
        self.observed = {}
        for path in self.files:
            self.path(path)

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
        if not isinstance(response, dict) or set(response) != {"edits"} or not isinstance(response["edits"], list):
            raise ValueError("Return exactly {edits: [{path, content}]}")
        staged, originals = {}, {}
        for edit in response["edits"]:
            if not isinstance(edit, dict) or set(edit) != {"path", "content"} or not all(isinstance(value, str) for value in edit.values()):
                raise ValueError("Each edit must contain string path and complete content")
            relative = edit["path"]
            target = self.path(relative)
            if relative not in self.writable:
                raise ValueError(f"File is not writable: {relative}")
            if relative in staged:
                raise ValueError(f"Duplicate edit path: {relative}")
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
        except (OSError, ValueError):
            for relative in reversed(written):
                if originals[relative] is None:
                    self.path(relative).unlink(missing_ok=True)
                else:
                    save_bytes(self.path(relative), originals[relative])
            raise
