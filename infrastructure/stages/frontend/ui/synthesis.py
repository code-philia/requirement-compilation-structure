"""Step 09 orchestration: retrieve pages, propose UI/data, validate, and publish.

All leaf requirements are designed before step 10 implements any UI. Reuse is
page-first: retrieval returns the corresponding UI/data subtree, not disconnected
components. Prompts and structural validation live in ui/design.py."""

import json

from infrastructure.stages.frontend.ui.design import INSTRUCTIONS, apply_proposal, empty_design, page_elements, validate_design
from infrastructure.shared.rag.pages import PageRetriever
from infrastructure.utils.files import save_json


def synthesize_ui(arc_dir, tree, schema, obligations, contracts, images, contexts, todos, model, console, top_k=3, max_fixtures=3):
    """Design UI/data for all leaf requirements using page-first retrieval.

    Show existing/retrieved pages, ask for an incremental proposal, and feed
    validation errors back for bounded retries. Save accepted ui_design.json
    updates; implementation and browser tests belong to step 10."""
    design, retriever = empty_design(), PageRetriever()
    for rid in tree.requirements:
        if tree.children[rid]:
            design["requirements"][rid] = []
            for sid in tree.own_steps[rid]:
                design["steps"][sid] = []
            console.show(f"{rid} | Skip non-leaf UI/data analysis", "Only leaf requirements are analyzed. Organizational parents do not generate or inherit UI nodes.")
    for number, rid in enumerate(tree.leaves, 1):
        requirement = contexts[rid]
        label = f"UI/data design {number}/{len(tree.leaves)} {rid}"
        console.show(label + " | 1. Requirement and steps", json.dumps(requirement, ensure_ascii=False, indent=2))
        console.show(label + " | 2. All Existing Pages", json.dumps(design["pages"], ensure_ascii=False, indent=2))
        retrieved = retriever.retrieve(requirement, design, top_k)
        console.show(label + " | 3. Retrieved page subtrees (RAG)", json.dumps(retrieved, ensure_ascii=False, indent=2))
        request = {
            "requirement": requirement, "retrieved_pages": retrieved["pages"],
            "all_pages": design["pages"], "schema": schema,
            "requirement_obligations": obligations["requirements"][rid],
            "step_obligations": {sid: obligations["steps"][sid] for sid in tree.own_steps[rid]},
            "direct_apis": {aid: contracts["apis"][aid] for aid in contracts["requirements"][rid]},
            "max_fixtures": max_fixtures,
            "upstream_todos": [todo for todo in todos if todo["requirement"] == rid],
        }
        for attempt in range(1, 4):
            response = None
            try:
                response = model.generate_json(INSTRUCTIONS, request)
                updated = apply_proposal(design, response, rid, tree, images, retrieved["pages"], max_fixtures)
                for image in requirement["images"]:
                    if not any(image in page["images"] and set(page_elements(updated, pid)).intersection(updated["requirements"][rid])
                            for pid, page in updated["pages"].items()):
                        raise ValueError(f"Requirement image needs a directly associated page subtree: {image}")
                break
            except ValueError as error:
                correction = {"error": str(error), "previous_response": response}
                message = str(error)
                if isinstance(error, json.JSONDecodeError):
                    correction["invalid_response"] = error.doc
                    correction["instruction"] = "Return one complete JSON object, not concatenated objects. Keep all pages/elements inside that object."
                    message += "\nInvalid JSON response (excerpt):\n" + error.doc[:3000]
                elif response is not None:
                    message += "\nRejected proposal (excerpt):\n" + json.dumps(response, ensure_ascii=False, indent=2)[:3000]
                console.show(label + f" | Validation failed ({attempt}/3)", message)
                if attempt == 3:
                    raise ValueError(f"UI/data design failed for {rid} after 3 proposals: {error}") from error
                request["correction"] = correction
        console.show(label + " | 4. Validated UI/data changes", json.dumps(response, ensure_ascii=False, indent=2))
        design = updated
    validate_design(design, tree, images, max_fixtures, complete=True)
    save_json(arc_dir / "ui_design.json", design)
    console.show("UI/data design complete for ALL requirements", f"Saved {arc_dir / 'ui_design.json'}\nRun 10_implement_ui.py for existence tests and UI implementation. Triggers and events are empty.")
    return design
