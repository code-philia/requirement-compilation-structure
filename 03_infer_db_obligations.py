"""Step 03: infer database read/write obligations for every requirement and step."""

import json
from contextlib import ExitStack
from pathlib import Path

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.shared.models.text import TextModel
from infrastructure.stages.database.obligations.records import normalize_inference, normalize_obligations
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.formatting import format_schema
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.presentation.formatting import format_obligations
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.utils.files import save_json
from infrastructure.shared.agent.proposals import propose_json


# --- Extension point 03A: obligation inference policy --------------------------
# Rewrite how requirement text maps to reads/writes, especially failure paths,
# fixture setup, and generated keys. Records are normalized for set operations.
INSTRUCTIONS = """Infer this requirement's database reads and writes over the supplied related_schema.
Return:
{
  "requirement": {"read": ["Entity.field"], "write": ["Entity.field"]},
  "steps": {"STEP-ID": {"read": ["Entity.field"], "write": ["Entity.field"]}}
}
"read" and "write" are separate fields containing arrays of qualified DB field names.
Use [] when a set is empty. Include the supplied step IDs; use steps={} when there
are no steps. Select existing schema symbols; do not create schema definitions.

Infer requirement effects from its description and complete scenarios. Infer each
step's effects from its own Given/When/Then and requirement context. Keep these
records independent: do not copy the requirement's writes into every step or force
parent/step containment equality. References provide context, not inherited effects.

Given fixtures describe existing state, not writes performed by the behavior under
test. Rejection and instructions to leave data unchanged do not imply writes.
Include lookup, filter and join keys in reads, and persisted generated keys in writes.
A field can occur in both arrays. Read/write sets describe possible behavior across
branches, not effects required on every invocation. Related fields are candidates;
there is no need to classify every supplied field. UI-only state has no DB effect.
For credentials, distinguish submitted passwords from stored hashes.
"""


def infer_db_obligations(arc_dir: Path, pause: bool = False, top_k: int = 6, max_attempts: int = 10) -> dict:
    for filename, previous in (("requirements.json", "01_explore_requirement.py"), ("db_schema.json", "02_build_db_schema.py")):
        if not (arc_dir / filename).is_file():
            raise ValueError(f"Run {previous} first to create .arc/{filename}")
    if top_k < 1:
        raise ValueError("--top-k must be positive")
    tree = RequirementTree(json.loads((arc_dir / "requirements.json").read_text(encoding="utf-8-sig")))
    schema = json.loads((arc_dir / "db_schema.json").read_text(encoding="utf-8-sig"))
    # --- Pass boundary: use the existing database symbol space ----------------
    # Inference may select existing fields, but cannot create schema symbols.
    # An unmapped concept should trigger schema review, not a fabricated field.
    console = DemoConsole(pause)
    model = TextModel()
    # Organizational parents keep empty records; only leaves receive model inference.
    obligations = {"requirements": {rid: {"read": [], "write": []} for rid in tree.requirements},
        "steps": {sid: {"read": [], "write": []} for sid in tree.steps}}

    for index, rid in enumerate(tree.leaves, 1):
        requirement = tree.requirements[rid]
        label = f"{index}/{len(tree.leaves)} {rid}"
        steps_text = tree.concatenated_steps(rid)
        console.show(f"{label} | 1. Current requirement and steps", (
            f"{requirement['name']}\n\nDescription:\n{requirement['description']}"
            f"\n\nConcatenated steps:\n{steps_text or '(No steps on this requirement.)'}"
        ))
        related_fields = schema["requirements"].get(rid)
        related_entities = {}
        for symbol in related_fields:
            entity, field = symbol.split(".", 1)
            related_entities.setdefault(entity, {"description": schema["entities"][entity]["description"], "fields": {}})
            related_entities[entity]["fields"][field] = schema["entities"][entity]["fields"][field]
        console.show(f"{label} | 2. Related schema fields", format_schema(related_entities))
        # --- Extension point 03C: inference granularity and feedback -----------
        # One call currently predicts a requirement and all its own steps.
        # Try separate calls or richer evidence, while retaining every node ID
        # and independent read/write sets. Do not repair containment here.
        request = {
            "requirement": requirement,
            "steps": [tree.steps[sid] for sid in tree.own_steps[rid]],
            "related_fields": sorted(related_fields),
            "related_schema": {"entities": related_entities},
        }
        def accept(response):
            inferred = normalize_inference(response, tree.own_steps[rid])
            summary = format_obligations({rid: inferred["requirement"], **inferred["steps"]})
            return inferred, summary

        (inferred, summary), _ = propose_json(model, INSTRUCTIONS, request, accept,
            console, f"Obligation inference {rid}", max_attempts)
        obligations["requirements"][rid] = inferred["requirement"]
        obligations["steps"].update(inferred["steps"])
        save_json(arc_dir / "db_obligations.json", obligations)
        console.artifact("db_obligations", obligations, f"{label} | Accepted obligations")
        console.show(f"{label} | 4. Inferred obligations", summary)

    obligations = normalize_obligations(obligations, tree)
    save_json(arc_dir / "db_obligations.json", obligations)
    print(f"Obligations saved: {arc_dir / 'db_obligations.json'}", flush=True)
    return obligations


def main() -> None:
    parser = create_parser("Step 03: Infer DB Obligations")
    parser.add_argument("--top-k", type=int, default=6, help="Number of BM25 entity/field hits (default: 6)")
    parser.add_argument("--max-attempts", type=int, default=10, help="Maximum proposals per requirement; including the first proposal (default: 10)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            infer_db_obligations(output_dir / ".arc", args.pause, args.top_k, args.max_attempts)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
