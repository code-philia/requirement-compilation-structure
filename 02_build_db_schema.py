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
from infrastructure.shared.agent.proposals import propose_json


# --- Extension point 02A: schema discovery policy ------------------------------
# Experiment with entity boundaries, reuse decisions, and constraint inference.
# Keep the upsert response compatible with infrastructure/stages/database/schema.py.
INSTRUCTIONS = """Design persistent data for the supplied requirement and its scenario steps.
Reuse the supplied retrieved entities and symbol_inventory; extend existing entities
rather than introducing synonyms for the same concept. Preserve unrelated definitions.
Store persistent business data, not transient UI values such as password confirmation.
Derive constraints from requirement evidence; example fixture values alone do not
establish uniqueness, normalization, value ranges or defaults.

Return {"entities": {...}, "related_fields": ["Entity.field"]}.
entities is an incremental update keyed by entity name. Each new entity contains
"description" (string) and "fields" (object keyed by field name).
Each new field contains these separate properties:
- description: string.
- type: string, integer, number, boolean, date, datetime, uuid or json.
- nullable, primary_key, unique: boolean properties.
- references: null or a qualified "Entity.field" string.
- constraints: array of descriptions of required value/domain constraints.
Use SQL-compatible entity/field identifiers. Represent keys and relationships needed
by the requirements, with compatible referenced field types. Password storage holds
hashes rather than plaintext. Do not invent unrelated business features.

For existing entities/fields, return only changed properties; omitted properties
are preserved by the compiler. Use references=null to clear a reference. Return
entities={} when existing definitions suffice. related_fields lists the qualified
persistent fields relevant to this requirement, including keys and relationships.
It is a schema association, not a read/write obligation. Use names from the resulting
schema.
"""


def requirement_nodes(root: dict):
    """Visit leaf requirements in document order; parents only organize the tree."""
    tree = RequirementTree(root)
    for rid in tree.leaves:
        yield {**tree.requirements[rid], "steps": tree.concatenated_steps(rid)}


def build_db_schema(arc_dir: Path, pause: bool = False, top_k: int = 6, max_attempts: int = 10) -> dict:
    requirements_path = arc_dir / "requirements.json"
    if not requirements_path.is_file():
        raise ValueError("Run 01_explore_requirement.py first to create .arc/requirements.json")
    requirements = json.loads(requirements_path.read_text(encoding="utf-8-sig"))
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

        # --- Extension point 02D: generation and JSON parse feedback -----------
        # Change the evidence supplied to the model or its correction strategy.
        # The name inventory is global; full definitions come from retrieval.
        # apply_patch() merges the proposed entity and field updates.
        request = {
            "requirement": requirement,
            "symbol_inventory": {name: list(entity["fields"]) for name, entity in schema["entities"].items()},
            "retrieved_schema": {"entities": retrieved["entities"]},
        }
        def accept(patch):
            updated = apply_patch(schema, patch)
            updated["requirements"][requirement["id"]] = sorted(set(patch["related_fields"]))
            changes = format_changes(schema, updated)
            return updated, changes

        (updated, changes), patch = propose_json(model, INSTRUCTIONS, request, accept,
            console, f"Schema design {requirement['id']}", max_attempts)
        # --- Pass boundary: publish the schema ----------------------
        # Subsequent requirements retrieve from this updated graph.
        save_json(arc_dir / "db_schema.json", updated)
        console.show(f"{label} | 4. Schema changes (saved)", (
            changes
        ))
        schema = updated
        console.artifact("db_schema", schema, f"{label} | Accepted schema")
    print(f"Schema saved: {arc_dir / 'db_schema.json'}", flush=True)
    return schema


def main() -> None:
    parser = create_parser("Step 02: Build DB Schema with RAG")
    parser.add_argument("--top-k", type=int, default=6, help="Number of BM25 entity/field hits (default: 6)")
    parser.add_argument("--max-attempts", type=int, default=10, help="Maximum proposals per requirement; including the first proposal (default: 10)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            build_db_schema(output_dir / ".arc", args.pause, args.top_k, args.max_attempts)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
