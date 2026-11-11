"""Step 02: discover entities and fields incrementally using schema RAG."""

import json
from pathlib import Path

from infrastructure.stages.database.schema_agent import SchemaAgent
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.formatting import format_changes, format_schema
from infrastructure.shared.rag.schema import SchemaRetriever
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.utils.files import save_json
from infrastructure.shared.agent.tasks import TaskFailures


def requirement_nodes(root: dict):
    """Visit leaf requirements in document order; parents only organize the tree."""
    tree = RequirementTree(root)
    nodes = {}
    parents = {}

    def visit(node, parent_name):
        nodes[node["id"]] = node
        parents[node["id"]] = parent_name
        for child in node.get("children", []) or []:
            visit(child, node.get("name", ""))

    visit(root, None)
    for rid in tree.leaves:
        yield {**tree.requirements[rid], "steps": tree.concatenated_steps(rid),
            "scenarios": nodes[rid].get("scenarios", []), "parent_module": parents[rid]}


def build_db_schema(arc_dir: Path, pause: bool = False, top_k: int = 10, max_attempts: int = 5) -> dict:
    requirements_path = arc_dir / "requirements.json"
    if not requirements_path.is_file():
        raise ValueError("Run main.py --stage 01 first to create .arc/requirements.json")
    requirements = json.loads(requirements_path.read_text(encoding="utf-8-sig"))
    # --- Extension point 02B: traversal and analysis context -------------------
    # RequirementTree owns traversal and step ownership. Study how another visit
    # order or richer node context changes the schema available to later nodes.
    nodes = list(requirement_nodes(requirements))
    if top_k < 1:
        raise ValueError("--top-k must be positive")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    console = DemoConsole(pause)
    retriever = SchemaRetriever()
    schema = {"entities": {}, "requirements": {}}
    failures = TaskFailures(arc_dir, "02_build_db_schema", console)
    save_json(arc_dir / "db_schema.json", schema)

    # for each requirement, retrieve relevant schema and propose an update
    for index, requirement in enumerate(nodes, 1):
        with failures.task(requirement["id"]):
            label = f"{index}/{len(nodes)} {requirement['id']}"
            console.show(f"{label} | 1. Current requirement", (
                f"{requirement['name']}\n\nDescription:\n{requirement['description']}"
                f"\n\nConcatenated steps:\n{requirement['steps'] or '(No steps on this requirement.)'}"
            ))
            console.show(f"{label} | 2. All existing schema (excerpt)", format_schema(schema["entities"], excerpt=True))

            # retrieve relevant schema using BM25; show matches and retrieved entities
            query = "\n".join(requirement[key] for key in ("name", "description", "steps"))
            retrieved = retriever.retrieve(query, schema, top_k)
            ranking = "\n".join(f"{item['symbol']}  BM25={item['score']:.4f}" for item in retrieved["matches"])
            console.show(f"{label} | 3. Retrieved schema", (
                (ranking or "No lexical matches (the schema may still be empty).")
                + "\n\nRetrieved entity definitions:\n"
                + format_schema(retrieved["entities"])
            ))

            # start the schema agent to propose a complete update, including related_fields
            agent = SchemaAgent(json_mode=False)
            try:
                updated = agent.run({"requirement": requirement, "schema": schema,
                    "retrieved_entities": retrieved["entities"]}, max_rounds=min(max_attempts, 5))
            finally:
                agent.model.client.close()
            changes = format_changes(schema, updated)

            # save the updated schema and show the changes
            save_json(arc_dir / "db_schema.json", updated)
            console.show(f"{label} | 4. Schema changes (saved)", (
                changes
            ))
            schema = updated
            console.artifact("db_schema", schema, f"{label} | Accepted schema")
    failures.finish()
    print(f"Schema saved: {arc_dir / 'db_schema.json'}", flush=True)
    return schema
