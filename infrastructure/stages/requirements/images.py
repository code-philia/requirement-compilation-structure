"""Resolve legacy images and published bundle UI screenshots without rewriting YAML."""

import hashlib
import json
import mimetypes
from pathlib import Path
import re

REFERENCE = re.compile(r"\\ref\[image\]\(([^)]+)\)")
FORMATS = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def requirement_nodes(root):
    yield root
    for child in root.get("children", []) or []:
        yield from requirement_nodes(child)


def node_images(node):
    """Normalize only image metadata; keep other structured evidence untouched."""
    description = node.get("description", {})
    if not isinstance(description, dict):
        return []
    images = []
    for field in ("image", "ui"):
        entries = description.get(field, [])
        if not isinstance(entries, list):
            raise ValueError(f"{node.get('id')}: description.{field} must be a list")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"{node.get('id')}: description.{field} entries must be objects")
            reference = entry.get("reference")
            if not isinstance(reference, str) or not reference.strip():
                raise ValueError(f"{node.get('id')}: description.{field} requires an image reference")
            if field == "image" and REFERENCE.fullmatch(reference):
                images.append(dict(entry))
                continue
            if not isinstance(entry.get("id"), str) or not entry["id"].strip():
                raise ValueError(f"{node.get('id')}: description.{field} requires an image ID")
            record = {**entry, "source_field": field}
            if field == "ui":
                if not isinstance(entry.get("name"), str) or not entry["name"].strip():
                    raise ValueError(f"{node.get('id')}: description.ui requires a page name")
                # This is a page hint, never a new route or a page for each capture.
                record["page"] = entry["name"]
            images.append(record)
    return images


def collect_images(root):
    """Return concrete paths in first-seen order; image macros are associations only."""
    return list(dict.fromkeys(
        image["reference"] for node in requirement_nodes(root) for image in node_images(node)
        if not REFERENCE.fullmatch(image["reference"])
    ))


def input_file(input_dir, reference):
    """Require a portable input-relative file, including through symlinks."""
    root = Path(input_dir).resolve()
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("Image reference must be a nonempty relative path")
    portable = reference.replace("\\", "/")
    if ":" in portable or Path(portable).is_absolute():
        raise ValueError(f"Image reference must be input-relative: {reference}")
    target = (root / portable).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError(f"Missing image or image escapes input: {reference}")
    return target


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot read image metadata {path}: {error}") from error


def build_image_catalog(root, input_dir):
    """Validate referenced screenshots, optional published index and ID associations.

    Only screenshot records in index.json are consumed. Routes, states, recipes,
    ER, permissions, processes and seed data are outside this parser's scope.
    """
    input_dir = Path(input_dir).resolve()
    nodes = list(requirement_nodes(root))
    definitions = [(node, image) for node in nodes for image in node_images(node)]
    published = None
    index_path = input_dir / "reference/ui/index.json"
    if any(image.get("source_field") == "ui" for _, image in definitions) and index_path.exists():
        index = read_json(input_file(input_dir, "reference/ui/index.json"))
        if not isinstance(index, dict) or index.get("schema_version") != 2:
            raise ValueError("UI screenshot index must have schema_version=2")
        captures = index.get("captures")
        if not isinstance(captures, list):
            raise ValueError("UI screenshot index requires a captures list")
        published = {}
        for capture in captures:
            if not isinstance(capture, dict) or not isinstance(capture.get("id"), str):
                raise ValueError("Invalid capture in UI screenshot index")
            if capture["id"] in published:
                raise ValueError(f"Duplicate published capture ID: {capture['id']}")
            published[capture["id"]] = capture
    images, requirements, hashes = {}, {}, {}
    for node, image in definitions:
        if REFERENCE.fullmatch(image["reference"]):
            continue
        source = input_file(input_dir, image["reference"])
        if mimetypes.guess_type(source.name)[0] not in FORMATS:
            raise ValueError(f"Unsupported image format: {image['reference']}")
        if source not in hashes:
            hashes[source] = hashlib.sha256(source.read_bytes()).hexdigest()
        record = {**image, "reference": source.relative_to(input_dir).as_posix(), "sha256": hashes[source]}
        iid = record["id"]
        if image.get("source_field") == "ui" and published is not None:
            capture = published.get(iid)
            if capture is None or capture.get("status") != "complete":
                raise ValueError(f"UI capture {iid} is missing or incomplete in index.json")
            files = capture.get("files")
            screenshot = files.get("screenshot") if isinstance(files, dict) else None
            if not isinstance(screenshot, dict):
                raise ValueError(f"UI capture {iid} has invalid screenshot metadata")
            indexed = input_file(input_dir, screenshot.get("path"))
            if indexed != source or screenshot.get("sha256") != record["sha256"]:
                raise ValueError(f"UI capture {iid} screenshot path or SHA256 does not match index.json")
        previous = images.get(iid)
        if previous and any(previous.get(key) != record.get(key) for key in ("reference", "page")):
            raise ValueError(f"Conflicting definitions for image ID {iid}")
        images[iid] = record
        requirements.setdefault(node["id"], [])
        if iid not in requirements[node["id"]]:
            requirements[node["id"]].append(iid)
    for node in nodes:
        direct = {key: value for key, value in node.items() if key != "children"}
        refs = REFERENCE.findall(json.dumps(direct, ensure_ascii=False))
        for iid in refs:
            if iid not in images:
                raise ValueError(f"{node.get('id')}: unknown image reference {iid}")
            requirements.setdefault(node["id"], [])
            if iid not in requirements[node["id"]]:
                requirements[node["id"]].append(iid)
    return {"images": images, "requirements": requirements}
