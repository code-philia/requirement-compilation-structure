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
    outline_path = output / ".arc/frontend_plan.json"
    if outline_path.is_file():
        outline = read_artifact(output / ".arc", outline_path.name)
        bindings = outline.get("requirements", {})
        pages = {pid for rid in requirements for pid in bindings.get(rid, [])}
        for rid, ids in bindings.items():
            if pages.intersection(ids):
                for stage in ("ui", "frontend"):
                    result.update(links.get(rid, {}).get(stage, []))
    for filename, stages in (("ui_design.json", ("ui", "frontend")),
            ("frontend_triggers.json", ("frontend",))):
        path = output / ".arc" / filename
        if outline_path.is_file() or not path.is_file():
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
    """Record edited files; references alone must not imply implementation ownership."""
    if not requirements or not paths:
        return
    path = output / ".arc" / FILE_LINKS
    links = read_artifact(output / ".arc", FILE_LINKS) if path.is_file() else {}
    for rid in requirements:
        stages = links.setdefault(rid, {})
        stages[stage] = sorted(set(stages.get(stage, [])) | set(paths))
    save_json(path, links)


def implementation_context(files):
    """Offer real landing points and shared consumers without another discovery stage."""
    output = files.output
    links_path = output / ".arc" / FILE_LINKS
    links = read_artifact(output / ".arc", FILE_LINKS) if links_path.is_file() else {}
    # Refresh after every edit; dependency reads are hints too, never exclusive ownership.
    relevant = files.related_files | set(files.read_files) | files.changed_paths
    owners = {}
    for rid, stages in links.items():
        for paths in stages.values():
            for path in set(paths) & relevant:
                if files.can_read(path) and files.path(path).is_file():
                    owners.setdefault(path, set()).add(rid)
    entrypoints = [path for path in (
        "backend/src/server.ts", "backend/src/app.ts", "backend/src/api/register.ts",
        "frontend/src/main.tsx", "frontend/src/App.tsx")
        if files.can_read(path) and files.path(path).is_file()]
    api_paths = {}
    mapping = output / ".arc/backend_implementation_files.json"
    if mapping.is_file():
        api_paths = {aid: path for aid, path in read_artifact(output / ".arc", mapping.name).items()
            if files.can_read(path) and files.path(path).is_file()}
    contract_path = output / ".arc/backend_endpoints.json"
    contracts = read_artifact(output / ".arc", contract_path.name) if contract_path.is_file() else {}
    api_locations = {}
    for aid, path in api_paths.items():
        api = contracts.get("apis", {}).get(aid, {})
        signature = api.get("signature", {})
        api_locations[aid] = {"path": path,
            "method": signature.get("method"), "route": signature.get("path"),
            "operation": signature.get("name"),
            "requirements": [rid for rid, ids in contracts.get("requirements", {}).items() if aid in ids]}
    return {"entrypoints": entrypoints, "api_implementations": api_locations,
        "file_requirements": {path: sorted(ids) for path, ids in sorted(owners.items())},
        "changed_files": sorted(files.changed_paths),
        "policy": "Reuse actual owners; connect every new module to a real caller; preserve shared consumers. "
                  "These paths are discovery hints, not a required file layout or exclusive write scope."}
