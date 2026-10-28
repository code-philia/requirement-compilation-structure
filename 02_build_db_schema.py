"""Step 02: discover entities and fields incrementally using schema RAG."""

import json
from contextlib import ExitStack
from pathlib import Path

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.formatting import format_changes, format_schema
from infrastructure.utils.presentation.logging import console_log
from infrastructure.shared.rag.schema import SchemaRetriever
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.database.schema import apply_patch
from infrastructure.utils.files import save_json


# --- Extension point 02A: schema discovery policy ------------------------------
# Experiment with entity boundaries, reuse decisions, and constraint inference.
# Keep the upsert response compatible with infrastructure/stages/database/schema.py.
INSTRUCTIONS = """Build a database schema for the current requirement only.
The schema is a graph: entities own fields, and fields reference Entity.field symbols.
Read the description AND all concatenated scenario steps, including failure cases.
Retrieved entities are authoritative existing definitions. Reuse them before adding
entities. Add missing fields to existing entities; do not create synonyms or duplicate
accounts for registration and login. Use the symbol inventory to avoid name collisions.
An existing entity may be modified only if it was retrieved. Preserve all untouched
entities and fields. Never rename or delete symbols or change existing field types.
Infer only persistent data justified by this requirement. Distinguish transient UI input
from stored data; for example, never persist password confirmation or plaintext passwords.
Include necessary primary and foreign keys; do not invent unrelated business features.
An unused example value in a Given clause does not by itself establish a uniqueness
rule. Do not invent trimming, normalization, value ranges, or default policies. Preserve
explicit comparison rules exactly. Refine earlier field constraints when the current
requirement gives more precise evidence; keep unrelated constraints unchanged.

Return exactly {"entities": {...}, "related_fields": [...], "explanation": "..."} in English.
entities is an incremental upsert patch keyed by entity name. Each new entity has
exactly description (nonempty string) and fields (object keyed by field name).
Each new field has exactly:
  description: nonempty string
  type: string|integer|number|boolean|date|datetime|uuid|json
  nullable: boolean
  primary_key: boolean
  unique: boolean
  references: null or "Entity.field"
  constraints: array of nonempty strings describing required value/domain constraints
Use identifiers matching [A-Za-z_][A-Za-z0-9_]*. Each entity must have exactly one
non-null primary key. Foreign keys must match their target type and reference a
primary or unique field. Represent many-to-many associations with a linking entity.
For existing entities and fields, include only new or changed properties; omitted
properties are preserved. Set references to null explicitly to clear an edge.
Return entities={} if the existing schema suffices, explaining what was reused.
Explain reuse, additions, and modifications using evidence from the current requirement.
If a correction is supplied, fix the reported error and return one complete JSON object.
Also return "related_fields": ["Entity.field", ...], listing every existing or newly
created field from this requirement's directly relevant persistent data. This is a
schema relationship, not a read/write obligation; include fields needed for identity,
lookups, joins, inserts, updates, and required session relationships. Do not include
unrelated fields. The compiler records this relation after validating the final schema.
"""


def requirement_nodes(root: dict):
    """Visit leaf requirements in document order; parents only organize the tree."""
    tree = RequirementTree(root)
    for rid in tree.leaves:
        yield {**tree.requirements[rid], "steps": tree.concatenated_steps(rid)}


def build_db_schema(arc_dir: Path, pause: bool = False, top_k: int = 6) -> dict:
    requirements_path = arc_dir / "requirements.json"
    if not requirements_path.is_file():
        raise ValueError("Run 01_explore_requirement.py first to create .arc/requirements.json")
    requirements = json.loads(requirements_path.read_text(encoding="utf-8"))
    # --- Extension point 02B: traversal and analysis context -------------------
    # RequirementTree owns traversal and step ownership. Study how another visit
    # order or richer node context changes the schema available to later nodes.
    nodes = list(requirement_nodes(requirements))
    if top_k < 1:
        raise ValueError("--top-k must be positive")
    console = DemoConsole(pause)
    retriever = SchemaRetriever()
    model = TextModel()
    schema = {"entities": {}, "requirements": {}}
    for index, requirement in enumerate(nodes, 1):
        label = f"{index}/{len(nodes)} {requirement['id']}"
        console.show(f"{label} | 1. Current requirement", (
            f"{requirement['name']}\n\nDescription:\n{requirement['description']}"
            f"\n\nConcatenated steps:\n{requirement['steps'] or '(No steps on this requirement.)'}"
        ))
        console.show(f"{label} | 2. All existing schema (excerpt)", format_schema(schema["entities"], excerpt=True))

        # --- Key extension point 02C: retrieval / RAG --------------------------
        # Rewrite query construction here and ranking/candidate selection in
        # infrastructure/shared/rag/schema.py: BM25, embeddings, hybrid search,
        # or reranking are possible experiments. Return {matches, entities};
        # retrieved entity definitions must retain their actual schema names.
        query = "\n".join(requirement[key] for key in ("name", "description", "steps"))
        retrieved = retriever.retrieve(query, schema, top_k)
        ranking = "\n".join(f"{item['symbol']}  BM25={item['score']:.4f}" for item in retrieved["matches"])
        console.show(f"{label} | 3. Retrieved schema", (
            (ranking or "No lexical matches (the schema may still be empty).")
            + "\n\nRetrieved entity definitions:\n"
            + format_schema(retrieved["entities"])
        ))

        # --- Extension point 02D: generation and validation feedback -----------
        # Change the evidence supplied to the model or its correction strategy.
        # The name inventory is global; full definitions come from retrieval.
        # apply_patch() checks the proposal before it can become shared state.
        request = {
            "requirement": requirement,
            "symbol_inventory": {name: list(entity["fields"]) for name, entity in schema["entities"].items()},
            "retrieved_schema": {"entities": retrieved["entities"]},
        }
        # Give malformed JSON or invalid graph updates bounded, explicit feedback.
        for attempt in range(1, 4):
            patch = None
            try:
                patch = model.generate_json(INSTRUCTIONS, request)
                if not isinstance(patch, dict) or not isinstance(patch.get("related_fields"), list):
                    raise ValueError("Model response must include related_fields")
                updated = apply_patch(schema, {key: patch[key] for key in ("entities", "explanation")}, retrieved["entities"])
                symbols = {f"{name}.{field}" for name, entity in updated["entities"].items() for field in entity["fields"]}
                if len(patch["related_fields"]) != len(set(patch["related_fields"])) or any(field not in symbols for field in patch["related_fields"]):
                    raise ValueError("related_fields must contain unique fields from the accepted schema")
                updated["requirements"][requirement["id"]] = sorted(patch["related_fields"])
                from infrastructure.stages.database.schema import validate_schema
                validate_schema(updated)
                break
            except ValueError as error:
                if attempt == 3:
                    raise ValueError(f"Schema analysis failed for {requirement['id']} after 3 attempts: {error}") from error
                print(f"Retrying {requirement['id']} ({attempt + 1}/3): {error}", flush=True)
                request["correction"] = {"error": str(error), "previous_patch": patch}
        # --- Pass boundary: publish the validated schema ----------------------
        # Subsequent requirements retrieve from this updated graph. Keep failed
        # proposals out of it so one mistake does not contaminate later nodes.
        save_json(arc_dir / "db_schema.json", updated)
        console.show(f"{label} | 4. Schema changes (validated and saved)", (
            patch["explanation"] + "\n\n" + format_changes(schema, updated)
        ))
        schema = updated
    print(f"Schema saved: {arc_dir / 'db_schema.json'}", flush=True)
    return schema


def main() -> None:
    parser = create_parser("Step 02: Build DB Schema with RAG")
    parser.add_argument("--top-k", type=int, default=6, help="Number of BM25 entity/field hits (default: 6)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir))
            build_db_schema(output_dir / ".arc", args.pause, args.top_k)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
