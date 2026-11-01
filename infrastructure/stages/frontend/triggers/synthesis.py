"""Design complete triggers, without frontend obligation or semantic gates."""

import json

from infrastructure.stages.frontend.triggers.prompts import INSTRUCTIONS
from infrastructure.stages.frontend.triggers.design import apply_decomposition, empty_triggers, relevant_pages, trigger_obligations, api_ids, validate_coverage
from infrastructure.utils.files import save_json, read_artifact
from infrastructure.stages.database.obligations.records import normalize_obligations
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.agent.discovery import ContextIndex
from infrastructure.shared.agent.conventions import load_conventions, select_conventions


def synthesize_triggers(arc_dir, ui, tree, backend, contexts, model, console, max_attempts=10):
    result = empty_triggers(tree)
    obligations = normalize_obligations(read_artifact(arc_dir, "db_obligations.json"), tree)
    accepted = []
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
        conventions = load_conventions(arc_dir)
        request = {"requirement": contexts[rid], "ui": local_ui,
            "required_obligations": obligations["requirements"][rid],
            "step_obligations": {sid: obligations["steps"][sid] for sid in tree.own_steps[rid]},
            "shared_conventions": select_conventions(conventions, requirements=[rid]),
            "existing_triggers": existing, "backend_apis": {aid: backend["apis"][aid] for aid in aids}}
        def accept(proposal):
            for sid in tree.own_steps[rid]:
                proposal["step_triggers"][sid]
            updated = apply_decomposition(result, proposal, rid)
            validate_coverage(updated, backend, obligations, tree, [*accepted, rid])
            derived = {tid: trigger_obligations(updated["triggers"][tid], backend)
                for tid in updated["requirements"][rid]}
            console.show(label + " | Derived DB effects", json.dumps(derived, ensure_ascii=False, indent=2))
            return updated

        result, _ = propose_json(model, INSTRUCTIONS, request, accept, console, label, max_attempts, context_index=ContextIndex(lambda: {"convention": conventions, "api": backend["apis"], "page": ui["pages"], "ui_element": ui["elements"], "binding": ui["bindings"], "trigger": result["triggers"]}))
        accepted.append(rid)
        console.artifact("frontend_triggers", result, label)
        save_json(arc_dir / "frontend_triggers.json", result)
    save_json(arc_dir / "frontend_triggers.json", result)
    return result
