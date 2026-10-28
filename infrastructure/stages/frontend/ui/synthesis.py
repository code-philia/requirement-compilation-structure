"""Step 09 orchestration: retrieve pages, propose UI/data, validate, and publish.

All leaf requirements are designed before step 10 implements any UI. Reuse is
page-first: retrieval returns the corresponding UI/data subtree, not disconnected
components. Prompts and structural validation live in ui/design.py."""

import json

from infrastructure.stages.frontend.ui.design import INSTRUCTIONS, apply_proposal, empty_design, page_elements, validate_design
from infrastructure.stages.frontend.ui.proposals import INSTRUCTIONS as PATCH_INSTRUCTIONS, validate_proposal
from infrastructure.shared.rag.pages import PageRetriever
from infrastructure.utils.files import save_json


def bind_requirement_image_pages(design, requirement, rid):
    """Bind image-backed pages to the current requirement when the page hint is unambiguous."""
    owned = set(design["requirements"].get(rid, []))
    images = requirement.get("images", {})
    image_records = images.values() if isinstance(images, dict) else images
    for image in image_records:
        if not isinstance(image, dict):
            continue
        image_id, page_hint = image.get("id"), image.get("page")
        # The requirement's explicit page hint is authoritative. The model may
        # omit the redundant page.images entry when creating a new page.
        if page_hint in design["pages"]:
            page = design["pages"][page_hint]
            page.setdefault("images", [])
            if image_id not in page["images"]:
                page["images"].append(image_id)
            candidates = [page_hint]
        else:
            candidates = [pid for pid, page in design["pages"].items() if image_id in page.get("images", [])]
        if len(candidates) != 1:
            continue
        root = design["pages"][candidates[0]]["root"]
        if root in design["elements"]:
            owned.add(root)
    design["requirements"][rid] = sorted(owned)


def synthesize_ui(arc_dir, tree, schema, obligations, contracts, images, contexts, model, console, top_k=3, max_fixtures=3):
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
            "all_pages": {pid: {key: page[key] for key in ("name", "route", "root", "images")}
                for pid, page in design["pages"].items()}, "schema": schema,
            "requirement_obligations": obligations["requirements"][rid],
            "step_obligations": {sid: obligations["steps"][sid] for sid in tree.own_steps[rid]},
            "direct_apis": {aid: contracts["apis"][aid] for aid in contracts["requirements"][rid]},
            "max_fixtures": max_fixtures,
        }
        for attempt in range(1, 4):
            response = None
            try:
                response = model.generate_json(INSTRUCTIONS + "\n\n" + PATCH_INSTRUCTIONS, request)
                proposal = validate_proposal(response, design, tree.own_steps[rid])
                updated = apply_proposal(design, proposal, rid, tree, images, retrieved["pages"], max_fixtures)
                bind_requirement_image_pages(updated, requirement, rid)
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
                    correction["instruction"] = "Follow the complete JSON examples exactly: one outer object containing pages, elements, bindings, requirement_ui, step_ui, explanation. Use ordinary objects, not patch/entries arrays. Keep the outer closing brace after explanation. Return only the incremental changes, not the accepted design."
                    message += "\nInvalid JSON response (excerpt):\n" + error.doc[:3000]
                elif response is not None:
                    message += "\nRejected proposal (excerpt):\n" + json.dumps(response, ensure_ascii=False, indent=2)[:3000]
                console.show(label + f" | Validation failed ({attempt}/3)", message)
                if attempt == 3:
                    raise ValueError(f"UI/data design failed for {rid} after 3 proposals: {error}") from error
                request["correction"] = correction
        console.show(label + " | 4. Validated incremental UI/data changes", json.dumps(proposal, ensure_ascii=False, indent=2))
        design = updated
    validate_design(design, tree, images, max_fixtures, complete=True)
    save_json(arc_dir / "ui_design.json", design)
    console.show("UI/data design complete for ALL requirements", f"Saved {arc_dir / 'ui_design.json'}\nRun 10_implement_ui.py for existence tests and UI implementation. Triggers and events are empty.")
    return design
