"""Create a minimal React/Express/SQLite workspace without replacing user files."""

from pathlib import Path
import json

from infrastructure.utils.files import save_json


DEFAULT_STACK = "react-express-sqlite"

# --- Extension point: technology stacks --------------------------------------
# Register another template directory and its empty directories here. New
# database/backend stacks also need matching lowering adapters in steps 05/08.
STACKS = {
    DEFAULT_STACK: {
        "templates": Path(__file__).with_name("templates"),
        "directories": ("backend/src/db/tables",),
    },
}


def enable_import_case_checks(output_dir: Path, workspace: str) -> str:
    """Upgrade existing TypeScript projects to detect case-dependent module imports."""
    relative = f"{workspace}/tsconfig.json"
    path = output_dir / relative
    configuration = json.loads(path.read_text(encoding="utf-8-sig"))
    options = configuration.setdefault("compilerOptions", {})
    if options.get("forceConsistentCasingInFileNames") is not True:
        options["forceConsistentCasingInFileNames"] = True
        save_json(path, configuration)
    return relative


def initialize_project(output_dir: Path, stack: str = DEFAULT_STACK) -> list[str]:
    # Templates contain infrastructure only. Existing application sources and
    # data are preserved; dependencies are installed separately by the TDD step.
    """Copy missing files from the chosen stack template and return their workspace-relative paths; preserve existing files."""
    if stack not in STACKS:
        raise ValueError(f"Unknown technology stack: {stack}. Available: {', '.join(STACKS)}")
    configuration = STACKS[stack]
    output_dir = output_dir.resolve()
    templates = configuration["templates"]
    if not templates.is_dir():
        raise ValueError(f"Stack templates do not exist: {templates}")
    created = []
    for source in sorted(templates.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(templates)
        target = output_dir / relative
        if not target.resolve().is_relative_to(output_dir):
            raise ValueError(f"Project path escapes the output directory: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(source.read_text(encoding="utf-8-sig"))
        except FileExistsError:
            if not target.is_file():
                raise ValueError(f"Expected a project file: {target}")
            continue
        created.append(relative.as_posix())
    for relative in configuration["directories"]:
        target = output_dir / relative
        if not target.resolve().is_relative_to(output_dir):
            raise ValueError(f"Project directory escapes the output directory: {relative}")
        target.mkdir(parents=True, exist_ok=True)
    return created
