"""Step 01: read the requirement tree, display every field, and analyze images."""

import json
import re
from pathlib import Path

import yaml

from infrastructure.shared.models.vision import VisualModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.files import save_json, save_text
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.requirements.images import (
    build_image_catalog, collect_images as collect_images, input_file, node_images,
)
from infrastructure.shared.project.git import checkpoint


OSC8_OPEN = "\x1b]8;;"
OSC8_CLOSE = "\x1b]8;;\x1b\\"
ESC = "\x1b\\"


def description_text(value: object) -> str:
    """Return the human-readable description from either supported YAML shape."""
    if isinstance(value, dict):
        value = value.get("text", "")
    return value if isinstance(value, str) else ""


def preorder_nodes(root: dict):
    """Yield raw requirement nodes in document-order preorder."""
    yield root
    for child in root.get("children", []) or []:
        yield from preorder_nodes(child)


def terminal_link(label: str, target: Path) -> str:
    """Render an OSC 8 hyperlink understood by modern terminal emulators."""
    return f"{OSC8_OPEN}{target.resolve().as_uri()}{ESC}{label}{OSC8_CLOSE}"


class RequirementExplorer:
    """Show one requirement at a time with optional scenario and step expansion."""

    def __init__(self, input_path: Path, root: dict) -> None:
        self.input_path = input_path.resolve()
        self.input_dir = self.input_path.parent
        self.tree = RequirementTree(root)
        self.nodes = list(preorder_nodes(root))
        self.console = DemoConsole()
        self.images = self._collect_images(root)

    def _collect_images(self, root: dict) -> dict[str, dict]:
        return build_image_catalog(root, self.input_dir)["images"]

    def _image_target(self, reference: object) -> tuple[str, Path | None, str | None]:
        """Resolve a requirement image while keeping file links inside input/."""
        if not isinstance(reference, str) or not reference.strip():
            return "(invalid image reference)", None, None
        source = Path(reference)
        target = source.resolve() if source.is_absolute() else (self.input_dir / source).resolve()
        if target != self.input_dir and self.input_dir not in target.parents:
            return reference, None, "outside input directory"
        if not target.is_file():
            return reference, target, "file not found"
        return reference, target, None

    def _references(self, references: object) -> list[tuple[str, Path | None, str | None]]:
        """Turn image IDs, reference macros, or direct image paths into link rows."""
        if not isinstance(references, list):
            return []
        result = []
        seen = set()
        for reference in references:
            if not isinstance(reference, str):
                continue
            match = re.search(r"ref\[image\]\(([^)]+)\)", reference, re.IGNORECASE)
            image_id = match.group(1) if match else reference
            image = self.images.get(image_id)
            raw_path = image.get("reference") if image else None
            if raw_path is None and Path(reference).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
                raw_path = reference
            if raw_path is None:
                continue
            label = image_id if image else Path(str(raw_path)).name
            display_path, target, problem = self._image_target(raw_path)
            key = (label, str(target) if target else display_path)
            if key not in seen:
                result.append((f"{label}  ·  {display_path}", target, problem))
                seen.add(key)
        return result

    @staticmethod
    def _requirement_images(node: dict) -> list:
        return node_images(node)

    def _print_links(self, rows: list[tuple[str, Path | None, str | None]]) -> None:
        for label, target, problem in rows:
            if target is not None and problem is None:
                print(f"  ↗ {terminal_link(label, target)}")
            else:
                suffix = f"  [{problem}]" if problem else ""
                print(f"  ↗ {label}{suffix}")

    def _show_node(self, node: dict, index: int, expanded: bool) -> None:
        rid = node["id"]
        requirement = self.tree.requirements[rid]
        depth = self._depth(rid)
        own_steps = self.tree.own_steps[rid]
        scenario_count = len(node.get("scenarios", []) or [])
        children = self.tree.children[rid]
        indent = "  " * depth
        body = [
            f"Preorder node {index + 1}/{len(self.nodes)}   ·   Depth {depth}",
            f"Requirement: {indent}{rid}  |  {requirement['name']}",
            "",
            "Description:",
            description_text(node.get("description", "")) or "(No description.)",
            "",
            f"Scenarios: {scenario_count}   ·   Steps: {len(own_steps)}   ·   Children: {len(children)}",
            "Child requirements: " + (", ".join(children) if children else "(none)"),
        ]
        self.console.show(f"Requirement | {rid} — {requirement['name']}", "\n".join(body))

        images = []
        for image in self._requirement_images(node):
            if isinstance(image, dict):
                label = image.get("id", "reference image")
                display_path, target, problem = self._image_target(image.get("reference"))
                images.append((f"{label}  ·  {display_path}", target, problem))
        if images:
            print("Reference images (click to open):")
            self._print_links(images)
        elif not expanded:
            print("Reference images: (none)")

        if expanded:
            self._show_scenarios(node)

    def _show_scenarios(self, node: dict) -> None:
        scenarios = node.get("scenarios", []) or []
        if not scenarios:
            self.console.show("Scenarios and steps", "This requirement has no scenarios or steps.")
            return
        for scenario in scenarios:
            sid = scenario.get("id", "Scenario")
            lines = [f"Scenario: {sid}  |  {scenario.get('name', '')}"]
            steps = scenario.get("steps", []) or []
            if not steps:
                lines.append("(No steps.)")
            for step in steps:
                lines.extend([
                    "",
                    f"Step: {step.get('id', '(no id)')}",
                    f"Given: {step.get('Given', step.get('given', ''))}",
                    f"When:  {step.get('When', step.get('when', ''))}",
                    f"Then:  {step.get('Then', step.get('then', ''))}",
                ])
                references = self._references(step.get("references", []))
                if references:
                    lines.append("Image references: " + ", ".join(row[0].split("  ·  ")[0] for row in references))
            self.console.show(f"Scenario | {sid}", "\n".join(lines))
            for step in steps:
                self._print_links(self._references(step.get("references", [])))

    def _depth(self, requirement_id: str) -> int:
        """Find a node's depth from the already-normalized containment tree."""
        def search(current: str, depth: int):
            if current == requirement_id:
                return depth
            for child in self.tree.children[current]:
                found = search(child, depth + 1)
                if found is not None:
                    return found
            return None

        return search(next(iter(self.tree.requirements)), 0) or 0

    def run(self) -> None:
        index = 0
        expanded = False
        while 0 <= index < len(self.nodes):
            self._show_node(self.nodes[index], index, expanded)
            prompt = "[Enter/n] next  [p] previous  [e] expand scenarios/steps  [c] collapse  [q] quit > "
            try:
                command = input(prompt).strip().lower()
            except EOFError:
                print()
                break
            if command in {"", "n", "next"}:
                index += 1
                expanded = False
            elif command in {"p", "prev", "previous"}:
                index = max(0, index - 1)
                expanded = False
            elif command in {"e", "expand"}:
                expanded = True
            elif command in {"c", "collapse"}:
                expanded = False
            elif command in {"q", "quit", "x"}:
                break
            else:
                print("Use Enter/n, p, e, c, or q.")
        print("Requirement browsing ended.")


def load_requirements(path: Path) -> dict:
    """Load YAML and validate its requirement/scenario/step IDs."""
    if not path.is_file():
        raise ValueError(f"Requirements file not found: {path}")
    try:
        root = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid requirements.yaml: {error}") from error
    if not isinstance(root, dict):
        raise ValueError("The requirements YAML root must be an object")
    seen = {"requirement": set(), "scenario": set(), "step": set()}

    def identify(record, kind):
        if not isinstance(record, dict):
            raise ValueError(f"Each {kind} must be an object")
        identifier = record.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError(f"Each {kind} requires a nonempty string ID")
        if identifier in seen[kind]:
            raise ValueError(f"Duplicate {kind} ID: {identifier}")
        seen[kind].add(identifier)

    def collection(record, key):
        value = record.get(key, [])
        if not isinstance(value, list):
            raise ValueError(f"{record.get('id')}: {key} must be a list")
        return value

    def validate(node):
        identify(node, "requirement")
        description = node.get("description", "")
        if not isinstance(description, (str, dict)):
            raise ValueError(f"{node['id']}: description must be text or an object")
        if isinstance(description, dict) and not isinstance(description.get("text", ""), str):
            raise ValueError(f"{node['id']}: description.text must be a string")
        for scenario in collection(node, "scenarios"):
            identify(scenario, "scenario")
            for step in collection(scenario, "steps"):
                identify(step, "step")
                for key in ("Given", "When", "Then"):
                    if not isinstance(step.get(key, step.get(key.lower())), str):
                        raise ValueError(f"{step['id']}: {key} must be a string")
        for child in collection(node, "children"):
            validate(child)

    validate(root)
    RequirementTree(root)
    return root


def explore_requirement(input_dir: Path, arc_dir: Path, pause: bool = False) -> dict:
    console = DemoConsole(pause)
    # --- Extension point 01A: requirement parsing -----------------------------
    # Try another source format or stronger syntax checks here. Preserve IDs,
    # containment, scenarios, and step text: later passes depend on these links.
    source = input_dir / "requirements.yaml"
    requirements = load_requirements(source)
    try:
        text = json.dumps(requirements, ensure_ascii=False, indent=2, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Cannot convert requirement fields to JSON: {error}") from error
    console.artifact("requirements", requirements, "1. Requirement tree")

    # --- Extension point 01B: reference discovery ------------------------------
    # Both legacy description.image and bundle description.ui use this resolver.
    # It validates only screenshot evidence, not other structured bundle fields.
    catalog = build_image_catalog(requirements, input_dir)
    references = list(dict.fromkeys(image["reference"] for image in catalog["images"].values()))
    console.show("2. Referenced images", "\n".join(references) or "(No referenced images.)")

    # --- Extension point 01C: visual analysis ----------------------------------
    # Rewrite the prompt/model in infrastructure/shared/models/vision.py to compare
    # visual extraction strategies. Keep {layout, elements, style}, or update
    # the response validator and downstream consumers together.
    arc_dir.mkdir(parents=True, exist_ok=True)
    save_text(arc_dir / "requirements.json", text + "\n")
    checkpoint(arc_dir.parent, stage="01", task="requirements", action="Publish input requirement snapshot",
        details={"source": str(source), "image_references": references})
    save_json(arc_dir / "image_references.json", catalog)
    analysis = {}
    analysis_sources = {}
    by_hash = {}
    hashes = {record["reference"]: record["sha256"] for record in catalog["images"].values()}
    if references:
        model = VisualModel()
        for reference in references:
            print(f"Analyzing image: {reference}", flush=True)
            digest = hashes[reference]
            if digest not in by_hash:
                by_hash[digest] = model.analyze(input_file(input_dir, reference))
            analysis[reference] = by_hash[digest]
            analysis_sources[reference] = digest
            save_json(arc_dir / "visual_analysis.json", analysis)
            save_json(arc_dir / "visual_analysis_sources.json", analysis_sources)
            checkpoint(arc_dir.parent, stage="01", task=reference, action="Publish visual reference analysis",
                details={"reference": reference, "analysis": analysis[reference]})
            console.show(f"3. Visual analysis | {reference}", json.dumps(analysis[reference], ensure_ascii=False, indent=2))
    else:
        console.show("3. Visual analysis", "No referenced images; no model call is needed.")
    save_json(arc_dir / "visual_analysis.json", analysis)
    save_json(arc_dir / "visual_analysis_sources.json", analysis_sources)
    print(f"Results saved: {arc_dir / 'requirements.json'}, {arc_dir / 'visual_analysis.json'}")
    return requirements
