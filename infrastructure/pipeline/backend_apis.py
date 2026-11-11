"""Design reusable HTTP APIs and internal modules for each leaf requirement."""

from pathlib import Path

from infrastructure.stages.backend.context import load_context, requirement_context
from infrastructure.stages.backend.design import validate_backend_design
from infrastructure.stages.backend.design_agent import BackendDesignAgent
from infrastructure.shared.rag.backend import BackendRetriever
from infrastructure.shared.agent.conventions import load_conventions, select_conventions
from infrastructure.shared.agent.tasks import TaskFailures
from infrastructure.utils.files import save_json
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.formatting import format_obligations


def design_backend_apis(arc_dir: Path, pause: bool = False, top_k: int = 6, max_attempts: int = 5) -> dict:
    tree, schema, obligations = load_context(arc_dir)
    if top_k < 1 or max_attempts < 1:
        raise ValueError("top_k and max_attempts must be positive")
    console = DemoConsole(pause)
    retriever = BackendRetriever()
    conventions = load_conventions(arc_dir)
    parents = {}
    for parent, children in tree.children.items():
        for child in children:
            parents[child] = tree.requirements[parent]["name"]
    design = {"apis": {}, "modules": {}, "requirements": {}, "requirement_modules": {}}
    for rid in tree.requirements:
        if tree.children[rid]:
            design["requirements"][rid] = []
            design["requirement_modules"][rid] = []
    failures = TaskFailures(arc_dir, "05_design_backend_apis", console)
    save_json(arc_dir / "backend_apis.json", design)
    for number, rid in enumerate(tree.leaves, 1):
        with failures.task(rid):
            requirement = {**requirement_context(tree, rid), "parent_module": parents.get(rid)}
            required = obligations["requirements"][rid]
            steps = {sid: obligations["steps"][sid] for sid in tree.own_steps[rid]}
            label = f"{number}/{len(tree.leaves)} {rid}"
            console.show(label + " | Backend design", requirement["description"] + "\n" + format_obligations({rid: required}))
            query = "\n".join((requirement["name"], requirement["description"], tree.concatenated_steps(rid)))
            retrieved = retriever.retrieve(query, required, design, top_k)
            console.show(label + " | Retrieved contracts",
                f"APIs: {', '.join(retrieved['apis']) or '(none)'}\n"
                f"Modules: {', '.join(retrieved['modules']) or '(none)'}")
            fields = set(required["read"]) | set(required["write"])
            for record in [*retrieved["apis"].values(), *retrieved["modules"].values()]:
                fields.update(record["read"])
                fields.update(record["write"])
            entities = {}
            for field in fields:
                name = field.split(".", 1)[0]
                entities[name] = schema["entities"][name]
            agent = BackendDesignAgent(json_mode=False)
            try:
                result = agent.run({"requirement": requirement, "step_obligations": steps,
                    "obligations": obligations, "schema": schema, "related_schema": entities,
                    "design": design, "tree": tree, "retrieved": retrieved,
                    "conventions": conventions,
                    "selected_conventions": select_conventions(conventions, fields=fields, requirements=[rid])},
                    max_rounds=min(max_attempts, 5))
            finally:
                agent.model.client.close()
            design, conventions = result["design"], result["conventions"]
            save_json(arc_dir / "backend_apis.json", design)
            save_json(arc_dir / "shared_conventions.json", conventions)
            console.artifact("backend_apis", design, label + " | Accepted APIs and modules")
    failures.finish()
    validate_backend_design(design, schema, obligations, tree, complete=True)
    save_json(arc_dir / "backend_apis.json", design)
    return design
