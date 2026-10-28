"""Step 11 design: retrieved UI/API context -> events -> typed event contracts.

Prompts describe trigger/event decomposition and Contract Inference. Validators
check obligation coverage and typed mappings before ui_interactions.json is
published. This module neither writes application code nor runs browser tests."""

import json

from infrastructure.stages.frontend.interactions.contracts import validate_contract
from infrastructure.stages.frontend.interactions.prompts import DECOMPOSE, contract_prompt, contract_targets
from infrastructure.stages.frontend.interactions.design import (InteractionCoverageError, apply_decomposition, empty_interactions,
    event_ids, relevant_pages, require_fields, text, validate_interactions)
from infrastructure.shared.rag.apis import ApiRetriever
from infrastructure.shared.rag.interactions import InteractionRetriever
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
        console.show(f"{label} | Model proposal {progress}", "Generate a proposal and validate its references, types, and mappings. Invalid proposals receive correction feedback.")
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


def synthesize_interactions(arc_dir, ui, tree, schema, obligations, backend, contexts, model, console, top_k=6, max_attempts=3):
    """Design triggers/events per leaf, then infer contracts for each shared event.

    Retrieve existing page events and APIs, validate obligation-union coverage,
    and show correction feedback. Publish ui_interactions.json only after the
    complete decomposition and all event contracts validate."""
    if max_attempts < 0:
        raise ValueError("--max-attempts must be nonnegative; use 0 for unlimited attempts")
    result, analyzed = empty_interactions(tree), []
    retriever, api_retriever = InteractionRetriever(), ApiRetriever()
    for rid in tree.requirements:
        if tree.children[rid]:
            console.show(rid + " | Skip non-leaf interaction analysis", "Parents retain empty direct bindings. Only leaf interaction decompositions are checked.")
    for number, rid in enumerate(tree.leaves, 1):
        label = f"Interaction Decomposition {number}/{len(tree.leaves)} {rid}"
        pages = relevant_pages(ui, rid)
        console.show(label + " | 1. Requirement, steps and DB obligations", json.dumps({
            "requirement": contexts[rid], "obligations": obligations["requirements"][rid],
            "steps": {sid: obligations["steps"][sid] for sid in tree.own_steps[rid]}}, ensure_ascii=False, indent=2))
        console.show(label + " | 2. Relevant page subtrees and frontend data", json.dumps(pages, ensure_ascii=False, indent=2))
        console.show(label + " | 3. All Existing Events", json.dumps({eid: event["description"] for eid, event in result["events"].items()}, ensure_ascii=False, indent=2))
        retrieved = retriever.retrieve(contexts[rid], pages, result, top_k)
        ranked = api_retriever.retrieve(json.dumps(contexts[rid], ensure_ascii=False), backend["apis"], top_k)
        allowed = backend["requirements"][rid]
        # Direct allocations are always included, even without lexical matches.
        api_context = {aid: backend["apis"][aid] for aid in allowed}
        console.show(label + " | 4. Retrieved interactions and allocated APIs (RAG)", json.dumps({
            "interactions": retrieved, "api_matches": ranked["matches"], "allowed_apis": api_context}, ensure_ascii=False, indent=2))
        request = {"requirement": contexts[rid], "page_subtrees": pages,
            "page_inventory": {pid: {"name": page["name"], "route": page["route"]} for pid, page in ui["pages"].items()},
            "retrieved_interactions": retrieved, "event_inventory": {eid: event["description"] for eid, event in result["events"].items()},
            "allowed_api_ids": allowed, "backend_apis": api_context, "api_matches": ranked["matches"],
            "obligations": obligations["requirements"][rid],
            "step_obligations": {sid: obligations["steps"][sid] for sid in tree.own_steps[rid]},
            "step_ui": {sid: ui["steps"][sid] for sid in tree.own_steps[rid]}}
        result, response = propose(model, DECOMPOSE, request,
            lambda value: apply_decomposition(result, value, rid, retrieved, ui, tree, schema, obligations, backend, analyzed), console, label, max_attempts)
        analyzed.append(rid)
        console.show(label + " | 5. Accepted triggers/events and obligation union", json.dumps({
            "explanation": response["explanation"], "triggers": {tid: result["triggers"][tid] for tid in result["requirements"][rid]},
            "events": {eid: result["events"][eid] for eid in sorted(event_ids(result, result["requirements"][rid]))}}, ensure_ascii=False, indent=2))
    validate_interactions(result, ui, tree, schema, obligations, backend, analyzed, complete=True)
    for number, eid in enumerate(result["events"], 1):
        label = f"Interaction Contract Inference {number}/{len(result['events'])} {eid}"
        tids = [tid for tid, trigger in result["triggers"].items() if trigger["action"] == eid]
        uses = [rid for rid, bindings in result["requirements"].items() if set(tids).intersection(bindings)]
        request = {"event_id": eid, "event": result["events"][eid],
            "triggers": {tid: result["triggers"][tid] for tid in tids},
            "all_requirement_uses": [contexts[rid] for rid in uses],
            "step_uses": {sid: tree.steps[sid] for sid, bindings in result["steps"].items() if set(tids).intersection(bindings)},
            "frontend_data": {var: {"binding": ui["bindings"][var], "descriptor": next(data for node in ui["elements"].values() for data in node.get("data", []) if data["var"] == var)}
                for var in set(result["events"][eid]["read"]) | set(result["events"][eid]["write"]) | {var for tid in tids for var in result["triggers"][tid]["read"]}},
            "page_inventory": {pid: {"route": page["route"], "name": page["name"]} for pid, page in ui["pages"].items()},
            "backend_apis": {action["api"]: backend["apis"][action["api"]] for action in result["events"][eid]["actions"] if action["kind"] == "api"}}
        request["validation_targets"] = contract_targets(eid, result, backend)
        console.show(label + " | Event, shared uses and fixed backend contracts", json.dumps(request, ensure_ascii=False, indent=2))

        def accept(value):
            """Attach a proposed event contract to a copy and validate it against the accepted decomposition."""
            require_fields(value, {"contract", "explanation"}, "Contract inference response")
            text(value["explanation"], "explanation")
            validate_contract(eid, value["contract"], result, ui, backend)
            return value["contract"]

        contract, response = propose(model, contract_prompt(result["events"][eid]), request, accept, console, label, max_attempts)
        result["contracts"][eid] = contract
        console.show(label + " | Validated P/Q and data mappings", json.dumps(response, ensure_ascii=False, indent=2))
    validate_interactions(result, ui, tree, schema, obligations, backend, analyzed, complete=True)
    if set(result["contracts"]) != set(result["events"]):
        raise ValueError("Every event needs exactly one canonical interaction contract")
    for eid, contract in result["contracts"].items():
        validate_contract(eid, contract, result, ui, backend)
    save_json(arc_dir / "ui_interactions.json", result)
    return result
