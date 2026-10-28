"""Persistent requirement/module associations for generated and edited files."""

import json
from copy import deepcopy
from pathlib import Path

from infrastructure.utils.files import save_json


class FileIndex:
    """Persistent requirement-to-file, module-to-file, and module-entrypoint associations."""
    def __init__(self, output: Path) -> None:
        """Load and validate .arc/file_index.json, or start an empty requirement/module/entrypoint index."""
        self.output = output.resolve()
        self.path = self.output / ".arc/file_index.json"
        self.data = json.loads(self.path.read_text()) if self.path.is_file() else {
            "requirements": {}, "modules": {}, "entrypoints": {},
        }
        if not isinstance(self.data, dict) or set(self.data) != {"requirements", "modules", "entrypoints"} or any(not isinstance(value, dict) for value in self.data.values()):
            raise ValueError("Invalid .arc/file_index.json")
        for kind in ("requirements", "modules"):
            for paths in self.data[kind].values():
                if not isinstance(paths, list):
                    raise ValueError("File associations must be lists")
                for path in paths:
                    self.validate_path(path)
        for entry in self.data["entrypoints"].values():
            if not isinstance(entry, dict) or set(entry) != {"path", "export"} or not isinstance(entry["export"], str):
                raise ValueError("Invalid module entrypoint")
            self.validate_path(entry["path"])

    def validate_path(self, relative: str) -> None:
        """Reject noncanonical paths and paths that resolve outside the generated workspace."""
        if not isinstance(relative, str) or not relative or "\\" in relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("File index paths must be workspace-relative")
        target = (self.output / relative).resolve()
        if not target.is_relative_to(self.output) or target.relative_to(self.output).as_posix() != relative or target == self.output:
            raise ValueError("File index paths must be canonical workspace-relative paths")

    def record(self, paths, requirements, module: str, entrypoint: dict | None = None, *, entrypoints: dict | None = None) -> None:
        """Atomically save file ownership and selected entrypoints, then replace the in-memory index."""
        entries = dict(entrypoints or {})
        if entrypoint is not None:
            entries[module] = entrypoint
        for identity, entry in entries.items():
            if not isinstance(identity, str) or not identity or not isinstance(entry, dict) or set(entry) != {"path", "export"}:
                raise ValueError("Invalid module entrypoint record")
            self.validate_path(entry["path"])
        paths = sorted(set(paths) | {entry["path"] for entry in entries.values()})
        for path in paths:
            self.validate_path(path)
        updated = deepcopy(self.data)
        for kind, identifiers in (("requirements", requirements), ("modules", [module])):
            for identifier in identifiers:
                updated[kind][identifier] = sorted(set(updated[kind].get(identifier, [])) | set(paths))
        for identity, entry in entries.items():
            updated["entrypoints"][identity] = dict(entry)
            updated["modules"][identity] = sorted(set(updated["modules"].get(identity, [])) | set(paths))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        save_json(self.path, updated)
        self.data = updated

    def files_for(self, requirements=(), module: str | None = None) -> list[str]:
        """Return sorted context paths associated with the selected requirements or module."""
        paths = set(self.data["modules"].get(module, []))
        for rid in requirements:
            paths.update(self.data["requirements"].get(rid, []))
        return sorted(paths)

    def forget_files(self, paths) -> None:
        """Remove retired compiler files from active requirement/module associations."""
        removed = set(paths)
        if any(entry["path"] in removed for entry in self.data["entrypoints"].values()):
            raise ValueError("Cannot retire a selected implementation entrypoint")
        updated = deepcopy(self.data)
        for kind in ("requirements", "modules"):
            for identity, files in updated[kind].items():
                updated[kind][identity] = [path for path in files if path not in removed]
        save_json(self.path, updated)
        self.data = updated
