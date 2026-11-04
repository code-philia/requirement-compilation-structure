"""Source discovery and ownership, independent of model file tools."""

from pathlib import Path
import os


SHARED_SOURCES = {"backend/src/api/register.ts", "backend/src/app.ts", "backend/src/server.ts",
    "frontend/src/main.tsx", "frontend/src/App.tsx", "frontend/src/ui-api.ts"}

EXCLUDED = {"node_modules", ".git", ".arc", "dist", "build", "coverage", "__pycache__", ".venv"}


def source_paths(output: Path, root: str) -> list[str]:
    """List text files in scope without walking dependencies or build directories."""
    result = []
    for directory, folders, filenames in os.walk(output / root, followlinks=False):
        folders[:] = [name for name in folders if name not in EXCLUDED and not name.startswith(".")
            and not (Path(directory) / name).is_symlink()]
        for name in filenames:
            path = Path(directory) / name
            if name.startswith(".") or path.is_symlink():
                continue
            if path.suffix in {".ts", ".tsx", ".js", ".jsx", ".css", ".json", ".html", ".sql", ".md"}:
                result.append(path.relative_to(output).as_posix())
    return sorted(result)


def editable_application_path(output, relative):
    """One ownership rule for existing and newly created application helpers."""
    templates = Path(__file__).resolve().parents[1] / "project/templates"
    if relative.startswith("frontend/src/"):
        return relative != "frontend/src/ui-runtime.ts"
    if relative.startswith("backend/src/"):
        return (relative in SHARED_SOURCES or (not (templates / relative).is_file()
            and not relative.startswith("backend/src/db/")))
    return (relative.startswith(("backend/tests/", "frontend/tests/"))
        and relative.endswith((".test.ts", ".spec.ts"))
        and "/tests/e2e/acceptance/" not in relative and not (templates / relative).is_file())
