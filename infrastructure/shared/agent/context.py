"""Requirement-to-file links and the small, common project context for implementation."""

from infrastructure.utils.files import read_artifact, save_json


FILE_LINKS = "requirement_files.json"


def related_files(output, requirements):
    """Load requirement files and already implemented shared pages/interactions."""
    index = output / ".arc" / FILE_LINKS
    links = read_artifact(output / ".arc", FILE_LINKS) if index.is_file() else {}
    result = set()
    for rid in requirements:
        for paths in links.get(rid, {}).values():
            result.update(paths)
    for filename, stages in (("ui_design.json", ("ui", "frontend")),
            ("frontend_triggers.json", ("frontend",))):
        path = output / ".arc" / filename
        if not path.is_file():
            continue
        design = read_artifact(output / ".arc", filename)
        bindings = design.get("requirements", {})
        symbols = {symbol for rid in requirements for symbol in bindings.get(rid, [])}
        if filename == "ui_design.json":
            # Different controls on one page still share the same component files.
            roots = {}
            for uid in design.get("elements", {}):
                current, visited = uid, set()
                while current in design["elements"] and current not in visited:
                    visited.add(current)
                    parent = design["elements"][current].get("parent")
                    if parent is None:
                        break
                    current = parent
                roots[uid] = current
            symbols = {roots.get(symbol, symbol) for symbol in symbols}
            bindings = {rid: [roots.get(symbol, symbol) for symbol in ids]
                for rid, ids in bindings.items()}
        for rid, ids in bindings.items():
            if not symbols.intersection(ids):
                continue
            for stage in stages:
                result.update(links.get(rid, {}).get(stage, []))
    schema = output / ".arc/db_schema.json"
    if schema.is_file():
        design = read_artifact(output / ".arc", "db_schema.json")
        entities = {field.split(".", 1)[0] for rid in requirements
            for field in design.get("requirements", {}).get(rid, [])}
        for entity in entities:
            for folder in ("tables", "seeds"):
                relative = f"backend/src/db/{folder}/{entity}.sql"
                if (output / relative).is_file():
                    result.add(relative)
    return result


def project_files(output, scope):
    """Use actual configuration and fixture paths; do not infer business filenames."""
    paths = {"package.json"}
    if any(directory.startswith("frontend") for directory in scope):
        paths.update(("frontend/package.json", "frontend/tsconfig.json", "frontend/vite.config.ts",
            "frontend/src/main.tsx", "frontend/src/App.tsx", "frontend/src/style.css",
            "frontend/src/ui-runtime.ts", "frontend/tests/e2e/support/context.ts"))
        paths.update(path.relative_to(output).as_posix()
            for path in (output / "frontend").glob("playwright*.config.*")
            if path.is_file() and not path.is_symlink())
    if any(directory.startswith("backend") for directory in scope):
        paths.update(("backend/package.json", "backend/tsconfig.json", "backend/tsconfig.test.json",
            "backend/src/app.ts", "backend/src/server.ts", "backend/src/api/register.ts",
            "backend/src/api/types.ts", "backend/src/db/client.ts", "backend/src/db/initialize.ts",
            "backend/src/db/seed.ts", "backend/tests/support/context.ts", "backend/scripts/test-api.mjs"))
    return {path for path in paths if (output / path).is_file()}


def record_files(output, requirements, stage, paths):
    """Record every known or edited file; a requirement may own any number of files."""
    if not requirements or not paths:
        return
    path = output / ".arc" / FILE_LINKS
    links = read_artifact(output / ".arc", FILE_LINKS) if path.is_file() else {}
    for rid in requirements:
        stages = links.setdefault(rid, {})
        stages[stage] = sorted(set(stages.get(stage, [])) | set(paths))
    save_json(path, links)
