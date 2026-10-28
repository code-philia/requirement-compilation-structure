"""Frontend inputs retain image/page evidence alongside normalized requirements."""

import json
import re

from infrastructure.stages.backend.context import load_context
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.utils.files import read_artifact
from infrastructure.stages.backend.contracts import validate_contracts
from infrastructure.stages.backend.primitives import validate_design
from infrastructure.stages.database.obligations.records import field_symbols

REFERENCE = re.compile(r"\\ref\[image\]\(([^)]+)\)")


def load_ui_design(arc_dir, tree, images):
    """Validate the saved design without rerunning synthesis or imposing a new fixture budget."""
    from infrastructure.stages.frontend.ui.design import validate_design as validate_ui_design

    design = read_artifact(arc_dir, "ui_design.json")
    if not isinstance(design, dict) or not isinstance(design.get("pages"), dict):
        raise ValueError("Saved UI design must contain a pages object")
    validate_ui_design(design, tree, images, max_fixtures=None, complete=True)
    return design


def load_ui_context(arc_dir, input_dir):
    """Load only requirement and image evidence; presentation does not depend on backend artifacts."""
    raw = read_artifact(arc_dir, "requirements.json")
    tree = RequirementTree(raw)
    analysis = read_artifact(arc_dir, "visual_analysis.json")
    images, nodes = {}, {}

    def visit(node):
        """Index raw requirements and their concrete image definitions, rejecting missing files or conflicting evidence."""
        nodes[node["id"]] = node
        description = node.get("description", {})
        for image in description.get("image", []) if isinstance(description, dict) else []:
            if not isinstance(image, dict) or not isinstance(image.get("id"), str) or not isinstance(image.get("reference"), str):
                raise ValueError("Each frontend image definition needs id and reference")
            if REFERENCE.fullmatch(image["reference"]):
                continue
            source = (input_dir / image["reference"]).resolve()
            if not source.is_relative_to(input_dir.resolve()) or not source.is_file():
                raise ValueError(f"Missing input image or image escapes input: {image['reference']}")
            if image["reference"] not in analysis:
                raise ValueError(f"Missing visual analysis: {image['reference']}; rerun step 01")
            record = {**image, "analysis": analysis[image["reference"]]}
            if image["id"] in images and images[image["id"]] != record:
                raise ValueError(f"Conflicting image definition: {image['id']}")
            images[image["id"]] = record
        for child in node.get("children", []):
            visit(child)

    visit(raw)
    contexts = {}
    for rid in tree.requirements:
        node = nodes[rid]
        direct = {key: value for key, value in node.items() if key != "children"}
        refs = set(REFERENCE.findall(json.dumps(direct)))
        description = node.get("description", {})
        for image in description.get("image", []) if isinstance(description, dict) else []:
            if image.get("id") in images:
                refs.add(image["id"])
        unknown = refs - set(images)
        if unknown:
            raise ValueError(f"Unknown image references at {rid}: {sorted(unknown)}")
        contexts[rid] = {**tree.requirements[rid], "steps": [tree.steps[sid] for sid in tree.own_steps[rid]],
            "images": {key: images[key] for key in sorted(refs)}}
    return tree, images, contexts


def load_frontend_context(arc_dir, input_dir):
    """Combine visual requirements with validated database and API artifacts for design stages."""
    tree, schema, obligations = load_context(arc_dir)
    _, images, contexts = load_ui_context(arc_dir, input_dir)
    backend = read_artifact(arc_dir, "backend_apis.json")
    contracts = read_artifact(arc_dir, "backend_contracts.json")
    validate_design(backend, obligations, field_symbols(schema), tree=tree)
    validate_contracts(contracts, backend)
    return tree, schema, obligations, contracts, images, contexts


def behavior_contexts(contexts):
    """Behavior stages use structured requirement text without repeated visual evidence."""
    return {rid: {key: value for key, value in context.items() if key != "images"}
        for rid, context in contexts.items()}
