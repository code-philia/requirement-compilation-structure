"""Render the shared runtime loader from the table implementation order."""

import json
from pathlib import Path


def initializer_source(implementations: dict) -> str:
    """Render the database initializer template with the SQL filenames in implementation order."""
    template = Path(__file__).resolve().parents[2] / "shared/project/templates/backend/src/db/initialize.ts"
    source = template.read_text(encoding="utf-8-sig")
    marker = "export const tableFiles: readonly string[] = [];"
    if marker not in source:
        raise ValueError("The DB initializer template is missing its table-list marker")
    files = [Path(item["path"]).name for item in implementations.values()]
    return source.replace(marker, "export const tableFiles: readonly string[] = " + json.dumps(files, indent=2) + ";")
