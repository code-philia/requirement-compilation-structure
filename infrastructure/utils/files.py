"""Atomic UTF-8/LF source publication and exact binary restoration across platforms."""

import json
from pathlib import Path
import re


def normalize_newlines(content: str) -> str:
    """Use LF internally, including when source or model edits contain CRLF/CR."""
    # CRCRLF is the common result of writing raw CRLF through Windows text I/O.
    # Preserve intentional LF blank lines while repairing repeated CR prefixes.
    return re.sub(r"\r+\n", "\n", content).replace("\r", "\n")


def read_source(path: Path) -> str:
    """Read UTF-8 source with optional BOM and normalize line endings for exact-text edits."""
    return normalize_newlines(path.read_bytes().decode("utf-8-sig"))


def save_bytes(path: Path, content: bytes) -> None:
    """Publish bytes atomically, including exact restoration of frozen/original files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save_json(path: Path, value: dict) -> None:
    """Publish indented UTF-8 JSON with LF line endings and no retained temporary file."""
    save_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def save_text(path: Path, content: str) -> None:
    """Create parent directories and publish UTF-8/LF source without OS newline translation."""
    save_bytes(path, normalize_newlines(content).encode("utf-8"))


def read_artifact(arc_dir: Path, filename: str) -> dict:
    """Load required UTF-8 JSON, accepting the BOM sometimes added by Windows editors."""
    path = arc_dir / filename
    if not path.is_file():
        raise ValueError(f"Missing .arc/{filename}; run the preceding compilation step first")
    return json.loads(path.read_text(encoding="utf-8-sig"))
