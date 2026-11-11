"""Derive requirement and step read/write obligations against the completed schema."""

import json
from pathlib import Path

from infrastructure.stages.database.obligation_agent import ObligationAgent
from infrastructure.shared.rag.schema import SchemaRetriever
from infrastructure.stages.database.obligation_utils import normalize_obligations
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.utils.files import save_json
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.formatting import format_schema, format_obligations
from infrastructure.shared.agent.tasks import TaskFailures


def infer_db_obligations(arc_dir: Path, pause: bool = False, top_k: int = 6, max_attempts: int = 5) -> dict:
    for filename in ("requirements.json", "db_schema.json"):
        if not (arc_dir / filename).is_file():
            raise ValueError(f"Missing prerequisite artifact: .arc/{filename}")
    if top_k < 1 or max_attempts < 1:
        raise ValueError("top_k and max_attempts must be positive")
    root = json.loads((arc_dir / "requirements.json").read_text(encoding="utf-8-sig"))
    tree = RequirementTree(root)
    schema = json.loads((arc_dir / "db_schema.json").read_text(encoding="utf-8-sig"))
    parents = {}

    def visit(node, parent_name):
        parents[node["id"]] = parent_name
        for child in node.get("children", []) or []:
            visit(child, node.get("name", ""))

    visit(root, None)
    console = DemoConsole(pause)
    retriever = SchemaRetriever()
    obligations = {"requirements": {}, "steps": {}}
    for rid in tree.requirements:
        if tree.children[rid]:
            obligations["requirements"][rid] = {"read": [], "write": []}
            for sid in tree.own_steps[rid]:
                obligations["steps"][sid] = {"read": [], "write": []}
    failures = TaskFailures(arc_dir, "03_infer_db_obligations", console)
    save_json(arc_dir / "db_obligations.json", obligations)

    # for each requirement, review its description and all its steps, then submit the complete obligation sets
    for number, rid in enumerate(tree.leaves, 1):
        with failures.task(rid):
            # requirement
            requirement = {**tree.requirements[rid], "parent_module": parents[rid]}
            steps = [tree.steps[sid] for sid in tree.own_steps[rid]]
            label = f"Review {number} | {rid}"
            console.show(label + " | Requirement review", requirement["description"] + "\n" + tree.concatenated_steps(rid))

            # related from last stage, not a complete boundary; may be empty
            candidates = schema["requirements"].get(rid, [])
            if not isinstance(candidates, list) or any(not isinstance(field, str) for field in candidates):
                raise ValueError(f"Malformed related_fields for {rid}")

            # retrieved related entities
            query = "\n".join((requirement["name"], requirement["description"], tree.concatenated_steps(rid)))
            retrieved = retriever.retrieve(query, schema, top_k)
            provided = dict(retrieved["entities"])
            for field in candidates:
                name = field.split(".", 1)[0]
                if name in schema["entities"]:
                    provided[name] = schema["entities"][name]
            console.show(label + " | Complete candidate and retrieved entities", format_schema(provided))

            # start the obligation agent
            agent = ObligationAgent(json_mode=False)
            try:
                reviewed = agent.run({"requirement": requirement, "steps": steps, "schema": schema,
                    "related_fields": candidates, "provided_entities": provided,
                    "matches": retrieved["matches"]}, max_rounds=min(max_attempts, 5))
            finally:
                agent.model.client.close()

            # save the reviewed obligation sets and show them
            obligations["requirements"][rid] = reviewed["requirement"]
            obligations["steps"].update(reviewed["steps"])
            save_json(arc_dir / "db_obligations.json", obligations)
            console.artifact("db_obligations", obligations, label + " | Accepted obligations")
            console.show(label + " | Reviewed effects", format_obligations({rid: reviewed["requirement"], **reviewed["steps"]}))

    failures.finish()
    obligations = normalize_obligations(obligations, tree)
    save_json(arc_dir / "db_obligations.json", obligations)
    return obligations
