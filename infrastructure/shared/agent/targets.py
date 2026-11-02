"""Task-specific destinations without embedding them in individual file tools."""

from dataclasses import dataclass
from pathlib import PurePosixPath

from infrastructure.shared.project.entrypoints import FILE_ROOTS, remember_path, selected_path


@dataclass
class FileTarget:
    kind: str
    identity: str
    directory: str
    path: str | None = None

    @classmethod
    def load(cls, output, kind, identity, existing=None, fixed_path=None):
        path = fixed_path or selected_path(output, kind, identity)
        if path is None and existing and (output / existing).is_file():
            path = existing
        directory = str(PurePosixPath(fixed_path).parent) if fixed_path else FILE_ROOTS[kind]
        return cls(kind, identity, directory, path)

    def context(self):
        return {"kind": self.kind, "id": self.identity, "directory": self.directory,
            "path": self.path, "instructions": "Use edit_file for this target. Preserve the supplied path; "
                "if path is null, choose a relative path inside directory. Create this target before new helpers."}

    def adapt(self, path):
        """Only adapt creation of the unambiguous current target, never arbitrary repairs."""
        if self.path is not None:
            return self.path
        if not path.startswith(self.directory + "/"):
            # Recover a missing layer prefix without losing nested subdirectories.
            tail = self.directory.split("/", 1)[-1]
            path = self.directory + "/" + (path[len(tail) + 1:] if path.startswith(tail + "/")
                else PurePosixPath(path).name)
        if "/tests/e2e/acceptance/" in path and self.kind != "acceptance_test":
            raise ValueError("Independent acceptance files belong to the separate acceptance task")
        suffix = {"backend_test": ".test.ts", "e2e_test": ".spec.ts"}.get(self.kind)
        if suffix and not path.endswith(suffix):
            stem = str(PurePosixPath(path).with_suffix(""))
            for ending in (".test", ".spec"):
                if stem.endswith(ending):
                    stem = stem[:-len(ending)]
            path = stem + suffix
        return path

    def bind(self, output, path):
        if self.kind in FILE_ROOTS:
            remember_path(output, self.kind, self.identity, path)
        self.path = path
