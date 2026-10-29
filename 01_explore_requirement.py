"""Step 01: read the requirement tree, display every field, and analyze images."""

import json
import re
from contextlib import ExitStack
from pathlib import Path

import yaml

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.shared.models.vision import VisualModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.files import save_json, save_text
from infrastructure.stages.requirements.tree import RequirementTree


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
        images = {}
        for node in self.nodes:
            description = node.get("description", {})
            if not isinstance(description, dict):
                continue
            refs = description.get("image", [])
            if not isinstance(refs, list):
                continue
            for image in refs:
                if isinstance(image, dict) and isinstance(image.get("id"), str):
                    images[image["id"]] = image
        return images

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
        description = node.get("description", {})
        return description.get("image", []) if isinstance(description, dict) else []

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
    RequirementTree(root)
    return root


def collect_images(value: object) -> list[str]:
    """Collect description.image references recursively in first-seen order."""
    references = []
    if isinstance(value, dict):
        description = value.get("description")
        if isinstance(description, dict):
            images = description.get("image", [])
            if not isinstance(images, list):
                raise ValueError("description.image must be a list")
            for image in images:
                if not isinstance(image, dict) or not isinstance(image.get("reference"), str):
                    raise ValueError("Each image must have a string reference")
                if not image["reference"].strip():
                    raise ValueError("Image reference must not be empty")
                references.append(image["reference"])
        for child in value.values():
            references.extend(collect_images(child))
    elif isinstance(value, list):
        for child in value:
            references.extend(collect_images(child))
    return list(dict.fromkeys(references))


def explore_requirement(input_dir: Path, arc_dir: Path, pause: bool = False) -> dict:
    console = DemoConsole(pause)
    # --- Extension point 01A: requirement parsing -----------------------------
    # Try another source format or stronger syntax checks here. Preserve IDs,
    # containment, scenarios, and step text: later passes depend on these links.
    source = input_dir / "requirements.yaml"
    try:
        requirements = yaml.safe_load(source.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid requirements.yaml: {error}") from error
    if not isinstance(requirements, dict):
        raise ValueError("The root of requirements.yaml must be a requirement object")
    try:
        text = json.dumps(requirements, ensure_ascii=False, indent=2, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Cannot convert requirement fields to JSON: {error}") from error
    console.show("1. Requirement tree", text)

    # --- Extension point 01B: reference discovery ------------------------------
    # collect_images() defines which references count as visual evidence.
    # Extend discovery for other document formats; keep paths input-relative.
    references = collect_images(requirements)
    for reference in references:
        image = (input_dir / reference).resolve()
        if not image.is_relative_to(input_dir.resolve()):
            raise ValueError(f"Referenced image must be inside the input directory: {reference}")
        if not image.is_file():
            raise ValueError(f"Referenced image does not exist: {reference}")
    console.show("2. Referenced images", "\n".join(references) or "(No referenced images.)")

    # --- Extension point 01C: visual analysis ----------------------------------
    # Rewrite the prompt/model in infrastructure/shared/models/vision.py to compare
    # visual extraction strategies. Keep {layout, elements, style}, or update
    # the response validator and downstream consumers together.
    arc_dir.mkdir(parents=True, exist_ok=True)
    save_text(arc_dir / "requirements.json", text + "\n")
    analysis = {}
    if references:
        model = VisualModel()
        for reference in references:
            print(f"Analyzing image: {reference}", flush=True)
            analysis[reference] = model.analyze(input_dir / reference)
            console.show(f"3. Visual analysis | {reference}", json.dumps(analysis[reference], ensure_ascii=False, indent=2))
    else:
        console.show("3. Visual analysis", "No referenced images; no model call is needed.")
    save_json(arc_dir / "visual_analysis.json", analysis)
    print(f"Results saved: {arc_dir / 'requirements.json'}, {arc_dir / 'visual_analysis.json'}")
    return requirements


def main() -> None:
    parser = create_parser("Step 01: Explore Requirement Tree")
    parser.add_argument(
        "--browse", action="store_true",
        help="Skip analysis and browse requirements interactively",
    )
    parser.add_argument(
        "--no-browse", action="store_true",
        help="Run analysis only (used by non-interactive pipelines)",
    )
    args = parser.parse_args()

    if args.browse and args.no_browse:
        parser.error("--browse and --no-browse cannot be used together")

    input_dir = args.input.expanduser().resolve()
    source = input_dir / "requirements.yaml"
    if args.browse:
        try:
            if not input_dir.is_dir():
                raise ValueError(f"Input directory does not exist or is not a directory: {input_dir}")
            root = load_requirements(source)
            RequirementExplorer(source, root).run()
        except (OSError, ValueError, yaml.YAMLError) as error:
            parser.exit(1, f"Cannot browse requirements: {error}\n")
        return

    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir))
            if not input_dir.is_dir():
                raise ValueError(f"Input directory does not exist or is not a directory: {input_dir}")
            requirements = explore_requirement(input_dir, output_dir / ".arc", args.pause)
            if not args.no_browse:
                RequirementExplorer(source, requirements).run()
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
