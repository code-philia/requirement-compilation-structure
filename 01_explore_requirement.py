"""Step 01: read the requirement tree, display every field, and analyze images."""

import json
from contextlib import ExitStack
from pathlib import Path

import yaml

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.shared.models.vision import VisualModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.files import save_json, save_text


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


def explore_requirement(input_dir: Path, arc_dir: Path, pause: bool = False) -> None:
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


def main() -> None:
    parser = create_parser("Step 01: Explore Requirement Tree")
    args = parser.parse_args()

    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir))
            if not input_dir.is_dir():
                raise ValueError(f"Input directory does not exist or is not a directory: {input_dir}")
            explore_requirement(input_dir, output_dir / ".arc", args.pause)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
