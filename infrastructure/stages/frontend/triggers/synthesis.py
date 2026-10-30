"""Design complete triggers, without frontend obligation or semantic gates."""

import json

from infrastructure.stages.frontend.triggers.prompts import INSTRUCTIONS
from infrastructure.stages.frontend.triggers.design import apply_decomposition, empty_triggers, relevant_pages, trigger_obligations
from infrastructure.utils.files import save_json
from infrastructure.shared.agent.proposals import propose_json


def synthesize_triggers(arc_dir, ui, tree, backend, contexts, model, console, max_attempts=10):
    result = empty_triggers(tree)
    for rid in tree.leaves:
        label = f"Trigger design {rid}"
        if not relevant_pages(ui, rid):
            continue
        request = {"requirement": contexts[rid], "ui": ui,
            "existing_triggers": result["triggers"], "backend_apis": backend["apis"]}
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
