"""Step 03: infer database read/write obligations for every requirement and step."""

import json
from contextlib import ExitStack
from pathlib import Path

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.shared.models.text import TextModel
from infrastructure.stages.database.obligations.records import field_symbols, validate_inference, validate_obligations
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.formatting import format_schema
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.presentation.formatting import format_obligations
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.database.schema import validate_schema
from infrastructure.utils.files import save_json


# --- Extension point 03A: obligation inference policy --------------------------
# Rewrite how requirement text maps to reads/writes, especially failure paths,
# fixture setup, and generated keys. The output contract is checked separately
# in infrastructure/stages/database/obligations/records.py.
INSTRUCTIONS = """Infer field-level dataflow obligations using only the related schema fields supplied for this requirement.
Return exactly this JSON object, in English:
{
  "requirement": {"read": ["Entity.field"], "write": ["Entity.field"]},
  "steps": {"STEP-ID": {"read": ["Entity.field"], "write": ["Entity.field"]}},
  "explanation": "Evidence for the requirement and each step's read/write choices.",
  "unmapped": []
}
Return every supplied step ID exactly once, and no other IDs; use steps={} when none
are supplied. All read/write entries must be existing qualified schema field symbols.
An empty set is []. Never create entities, fields, or substitute a similar but wrong field.
Use only the supplied related schema definitions to bind data concepts.
If necessary persistent data cannot be mapped, list the concepts in unmapped. Do not
silently omit them or clear unmapped merely to pass validation. UI-only state need not
map to persistent fields. Password input is verified against a hash, not stored plaintext.

Infer the requirement's obligations from its description and overall scenario behavior.
Independently infer each step's actual reads/writes using its Given, When, Then and
the owning requirement's context. Requirement and step obligations are independent;
do not force containment equality or propagate effects between nodes. Never copy
the requirement's writes into every step.
Given fixtures describe existing state, not writes performed by the current behavior.
An instruction to leave data unchanged is not a write. Rejection/failure steps that
create no account or session have no such writes. A field can appear in both sets if
the behavior reads and modifies it. Include necessary keys for lookups, relationships,
and inserted records. A generated primary key is still a persisted write when inserting
a record; do not exclude it as "system-generated" or "not business data". Lookup/filter
and join keys are reads even when they are not displayed. Do not read every field merely
because the entity is retrieved.
The requirement read/write union must cover every supplied related field. A field may
appear in both sets when the behavior reads and modifies it. If any related field is
not classified, the proposal is invalid and must be corrected. References are context
only in this pass; do not blindly inherit another node's effects.
If a correction is supplied, fix the error and return one complete JSON object.
"""


def infer_db_obligations(arc_dir: Path, pause: bool = False, top_k: int = 6) -> dict:
    for filename, previous in (("requirements.json", "01_explore_requirement.py"), ("db_schema.json", "02_build_db_schema.py")):
        if not (arc_dir / filename).is_file():
            raise ValueError(f"Run {previous} first to create .arc/{filename}")
    if top_k < 1:
        raise ValueError("--top-k must be positive")
    tree = RequirementTree(json.loads((arc_dir / "requirements.json").read_text(encoding="utf-8")))
    schema = json.loads((arc_dir / "db_schema.json").read_text(encoding="utf-8"))
    validate_schema(schema)
    # --- Pass boundary: use the existing database symbol space ----------------
    # Inference may select existing fields, but cannot create schema symbols.
    # An unmapped concept should trigger schema review, not a fabricated field.
    symbols = field_symbols(schema)
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
        if not isinstance(related_fields, list):
            raise ValueError(f"Missing schema relation for requirement: {rid}; rerun step 02")
        related_entities = {}
        for symbol in related_fields:
            entity, field = symbol.split(".", 1)
            related_entities.setdefault(entity, {"description": schema["entities"][entity]["description"], "fields": {}})
            related_entities[entity]["fields"][field] = schema["entities"][entity]["fields"][field]
        related_symbols = set(related_fields)
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
        for attempt in range(1, 4):
            response = None
            try:
                response = model.generate_json(INSTRUCTIONS, request)
                inferred = validate_inference(response, related_symbols, tree.own_steps[rid])
                classified = set(inferred["requirement"]["read"]) | set(inferred["requirement"]["write"])
                if classified != related_symbols:
                    raise ValueError(f"Requirement obligation coverage mismatch: missing={sorted(related_symbols - classified)}, extra={sorted(classified - related_symbols)}")
                break
            except ValueError as error:
                if attempt == 3:
                    raise ValueError(f"Obligation inference failed for {rid} after 3 attempts: {error}") from error
                print(f"Retrying {rid} ({attempt + 1}/3): {error}", flush=True)
                request["correction"] = {"error": str(error), "previous_response": response}
        obligations["requirements"][rid] = inferred["requirement"]
        obligations["steps"].update(inferred["steps"])
        console.show(f"{label} | 4. Inferred obligations (symbol-checked)", (
            response["explanation"] + "\n\n"
            + format_obligations({rid: inferred["requirement"], **inferred["steps"]})
        ))

    obligations = validate_obligations(obligations, tree, field_symbols(schema))
    save_json(arc_dir / "db_obligations.json", obligations)
    print(f"Obligations saved: {arc_dir / 'db_obligations.json'}", flush=True)
    return obligations


def main() -> None:
    parser = create_parser("Step 03: Infer DB Obligations")
    parser.add_argument("--top-k", type=int, default=6, help="Number of BM25 entity/field hits (default: 6)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir))
            infer_db_obligations(output_dir / ".arc", args.pause, args.top_k)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
