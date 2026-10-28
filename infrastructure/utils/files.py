"""Atomic publication of JSON artifacts and generated source files.

These helpers know nothing about requirements, models, or compilation stages.
"""

import json
from pathlib import Path


def save_json(path: Path, value: dict) -> None:
    """Atomically publish indented UTF-8 JSON; the caller creates the parent directory and temporary files are always removed."""
    temporary = path.with_name(f".{path.stem}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)

def save_text(path: Path, content: str) -> None:
    """Create parent directories and atomically publish UTF-8 source text, removing temporary files even on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_artifact(arc_dir: Path, filename: str) -> dict:
    """Load one required .arc JSON artifact, reporting a missing prerequisite before model work begins."""
    path = arc_dir / filename
    if not path.is_file():
        raise ValueError(f"Missing .arc/{filename}; run the preceding compilation step first")
    return json.loads(path.read_text(encoding="utf-8"))
