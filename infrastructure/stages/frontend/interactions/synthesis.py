"""Step 11: simple trigger/action design followed by shared event P/Q inference."""

import json

from infrastructure.stages.frontend.interactions.contracts import validate_contract
from infrastructure.stages.frontend.interactions.prompts import DECOMPOSE, CONTRACT
from infrastructure.stages.frontend.interactions.design import (InteractionCoverageError, apply_decomposition, empty_interactions,
    event_ids, relevant_pages, require_fields, validate_interactions)
from infrastructure.utils.files import save_json


def propose(model, instructions, request, validate, console, label, max_attempts=3):
    """Retry proposals with validation feedback; zero removes the attempt limit."""
    if max_attempts < 0:
        raise ValueError("--max-attempts must be nonnegative; use 0 for unlimited attempts")
    attempt = 0
    while True:
        attempt += 1
        response = None
        progress = f"{attempt}/{max_attempts}" if max_attempts else f"{attempt} (unlimited)"
        console.show(f"{label} | Model proposal {progress}", "Generate a proposal and validate its references, effects and semantic conditions. Invalid proposals receive correction feedback.")
        try:
            response = model.generate_json(instructions, request)
            return validate(response), response
        except ValueError as error:
            correction = {"error": str(error), "previous_response": response}
            if isinstance(error, InteractionCoverageError):
                correction["obligation_coverage"] = error.feedback
            if isinstance(error, json.JSONDecodeError):
                correction["invalid_response"] = error.doc
            console.show(f"{label} | Validation failed", json.dumps(correction, ensure_ascii=False, indent=2))
            if max_attempts and attempt >= max_attempts:
                raise ValueError(f"{label} failed after {max_attempts} proposals: {error}") from error
            request["correction"] = correction


def synthesize_interactions(arc_dir, ui, tree, schema, obligations, backend, contexts, model, console, max_attempts=3):
    """Design each leaf once, then infer one canonical P/Q per shared event."""
    result, analyzed = empty_interactions(tree), []
    inventory = {pid: {"name": page["name"], "route": page["route"]} for pid, page in ui["pages"].items()}
    for rid in tree.leaves:
        label = f"Interaction design {rid}"
        pages = relevant_pages(ui, rid)
        if not pages:
            analyzed.append(rid)
            console.show(label + " | No UI", "No frontend interactions are needed for this requirement.")
            continue
        request = {"requirement": contexts[rid], "page_subtrees": pages,
            "page_inventory": inventory,
            "existing_interactions": {kind: result[kind] for kind in ("events", "triggers")},
            "backend_apis": {aid: backend["apis"][aid] for aid in backend["requirements"][rid]},
            "frontend_data": ui["bindings"],
            "obligations": obligations["requirements"][rid],
            "step_ui": {sid: ui["steps"][sid] for sid in tree.own_steps[rid]}}
        result, response = propose(model, DECOMPOSE, request,
            lambda value: apply_decomposition(result, value, rid, ui, tree, schema, obligations, backend, analyzed),
            console, label, max_attempts)
        analyzed.append(rid)
        console.show(label + " | Accepted", json.dumps(response, ensure_ascii=False, indent=2))
    validate_interactions(result, ui, tree, schema, obligations, backend, analyzed, complete=True)
    for eid, event in result["events"].items():
        tids = {tid for tid, trigger in result["triggers"].items() if trigger["action"] == eid}
        uses = [rid for rid, ids in result["requirements"].items() if tids.intersection(ids)]
        request = {"event_id": eid, "event": event,
            "triggers": {tid: result["triggers"][tid] for tid in sorted(tids)},
            "all_requirement_uses": [contexts[rid] for rid in uses],
            "frontend_data": ui["bindings"], "page_inventory": inventory,
            "backend_apis": {aid: backend["apis"][aid] for aid in sorted({action["api"] for action in event["actions"] if action["kind"] == "api"})}}

        def accept(value):
            require_fields(value, {"contract"}, "Event contract response")
            validate_contract(eid, value["contract"])
            return value["contract"]

        result["contracts"][eid], _ = propose(model, CONTRACT, request, accept, console,
            f"Event P/Q {eid}", max_attempts)
    save_json(arc_dir / "ui_interactions.json", result)
    return result
