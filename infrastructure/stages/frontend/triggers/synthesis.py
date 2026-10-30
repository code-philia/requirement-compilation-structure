"""Design complete triggers, without frontend obligation or semantic gates."""

import json

from infrastructure.stages.frontend.triggers.prompts import INSTRUCTIONS
from infrastructure.stages.frontend.triggers.design import apply_decomposition, empty_triggers, relevant_pages
from infrastructure.utils.files import save_json


def synthesize_triggers(arc_dir, ui, tree, backend, contexts, model, console, max_attempts=3):
    result = empty_triggers(tree)
    for rid in tree.leaves:
        label = f"Trigger design {rid}"
        if not relevant_pages(ui, rid):
            continue
        request = {"requirement": contexts[rid], "ui": ui,
            "existing_triggers": result["triggers"], "backend_apis": backend["apis"]}
        attempt = 0
        while True:
            attempt += 1
            console.show(label, f"Model proposal {attempt}")
            try:
                proposal = model.generate_json(INSTRUCTIONS, request)
                break
            except json.JSONDecodeError as error:
                if max_attempts and attempt >= max_attempts:
                    raise
                request["correction"] = {"error": str(error), "invalid_response": error.doc}
        result = apply_decomposition(result, proposal, rid)
        console.artifact("frontend_triggers", result, label)
        save_json(arc_dir / "frontend_triggers.json", result)
    save_json(arc_dir / "frontend_triggers.json", result)
    return result
