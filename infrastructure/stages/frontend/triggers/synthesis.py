"""Design requirement-scoped triggers after checking upstream API capabilities."""

import json

from infrastructure.stages.frontend.triggers.prompts import INSTRUCTIONS
from infrastructure.stages.frontend.triggers.design import apply_decomposition, empty_triggers, relevant_pages, trigger_obligations, api_ids, validate_coverage
from infrastructure.stages.frontend.ui.design import data_symbols
from infrastructure.utils.files import save_json, read_artifact
from infrastructure.stages.database.obligations.records import normalize_obligations
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.agent.tasks import TaskFailures
from infrastructure.shared.agent.discovery import ContextIndex
from infrastructure.shared.agent.conventions import load_conventions, select_conventions
from infrastructure.stages.backend.primitives import validate_design, ObligationCoverageError


def synthesize_triggers(arc_dir, ui, tree, backend, contexts, model, console, max_attempts=10):
    result = empty_triggers(tree)
    obligations = normalize_obligations(read_artifact(arc_dir, "db_obligations.json"), tree)
    accepted = []
    failures = TaskFailures(arc_dir, "11_design_frontend_triggers", console)
    save_json(arc_dir / "frontend_triggers.json", result)
    for rid in tree.leaves:
        with failures.task(rid):
            label = f"Trigger design {rid}"
            if not relevant_pages(ui, rid):
                continue
            try:
                validate_design({"apis": backend["apis"],
                    "requirements": {rid: backend["requirements"].get(rid, [])}},
                    obligations, complete=False, tree=tree)
            except ObligationCoverageError as error:
                raise ValueError(f'Upstream backend contract cannot cover {rid}: {error}. '
                    'Review stage 03 obligations and stage 06 API design before generating triggers.') from error
            pages = relevant_pages(ui, rid)
            elements = {uid for page in pages.values() for uid in page["elements"]}
            local_ui = {**ui, "pages": {pid: ui["pages"][pid] for pid in pages},
                "elements": {uid: ui["elements"][uid] for uid in elements},
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

            result, _ = propose_json(model, INSTRUCTIONS, request, accept, console, label, max_attempts, context_index=ContextIndex(lambda: {"convention": conventions, "api": backend["apis"], "page": ui["pages"], "ui_element": ui["elements"], "ui_data": data_symbols(ui["elements"]), "trigger": result["triggers"]}))
            accepted.append(rid)
            console.artifact("frontend_triggers", result, label)
            save_json(arc_dir / "frontend_triggers.json", result)
    failures.finish()
    save_json(arc_dir / "frontend_triggers.json", result)
    return result
