"""Design complete triggers, without frontend obligation or semantic gates."""

import json

from infrastructure.stages.frontend.triggers.prompts import INSTRUCTIONS
from infrastructure.stages.frontend.triggers.design import apply_decomposition, empty_triggers, relevant_pages, trigger_obligations, api_ids
from infrastructure.utils.files import save_json
from infrastructure.shared.agent.proposals import propose_json


def synthesize_triggers(arc_dir, ui, tree, backend, contexts, model, console, max_attempts=10):
    result = empty_triggers(tree)
    for rid in tree.leaves:
        label = f"Trigger design {rid}"
        if not relevant_pages(ui, rid):
            continue
        pages = relevant_pages(ui, rid)
        elements = {uid for page in pages.values() for uid in page["elements"]}
        local_ui = {**ui, "pages": {pid: ui["pages"][pid] for pid in pages},
            "elements": {uid: ui["elements"][uid] for uid in elements},
            "bindings": {key: value for page in pages.values() for key, value in page["bindings"].items()},
            "requirements": {rid: ui["requirements"].get(rid, [])},
            "steps": {sid: ui["steps"].get(sid, []) for sid in tree.own_steps[rid]}}
        existing = {tid: trigger for tid, trigger in result["triggers"].items() if trigger["source"] in elements}
        aids = set(backend["requirements"].get(rid, [])) | {aid for trigger in existing.values() for aid in api_ids(trigger)}
        request = {"requirement": contexts[rid], "ui": local_ui,
            "existing_triggers": existing, "backend_apis": {aid: backend["apis"][aid] for aid in aids}}
        def accept(proposal):
            updated = apply_decomposition(result, proposal, rid)
            derived = {tid: trigger_obligations(updated["triggers"][tid], backend)
                for tid in updated["requirements"][rid]}
            console.show(label + " | Derived DB effects", json.dumps(derived, ensure_ascii=False, indent=2))
            return updated

        result, _ = propose_json(model, INSTRUCTIONS, request, accept, console, label, max_attempts)
        console.artifact("frontend_triggers", result, label)
        save_json(arc_dir / "frontend_triggers.json", result)
    save_json(arc_dir / "frontend_triggers.json", result)
    return result
