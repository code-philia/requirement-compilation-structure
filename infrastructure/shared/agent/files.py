"""Source discovery and ownership, independent of model file tools."""

from pathlib import Path


SHARED_SOURCES = {"backend/src/api/register.ts", "backend/src/app.ts", "backend/src/server.ts",
    "frontend/src/main.tsx", "frontend/src/App.tsx", "frontend/src/ui-api.ts"}

EXCLUDED = {"node_modules", ".git", ".arc", "dist", "build", "coverage", "__pycache__", ".venv"}


def source_paths(output: Path, root: str) -> list[str]:
    """Supply text sources from a fixed project directory without a file association index."""
    return sorted(path.relative_to(output).as_posix() for path in (output / root).rglob("*")
        if path.is_file() and not path.is_symlink()
        and not any(part.startswith(".") or part in EXCLUDED for part in path.relative_to(output).parts)
        and path.suffix in {".ts", ".tsx", ".js", ".jsx", ".css", ".json", ".html", ".sql", ".md"})


def editable_sources(output: Path, root: str) -> list[str]:
    """Allow application repairs while protecting compiler-owned infrastructure."""
    return [relative for relative in source_paths(output, root) if editable_application_path(output, relative)]


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
