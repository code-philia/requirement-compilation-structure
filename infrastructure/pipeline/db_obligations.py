"""Step 03: infer database read/write obligations for every requirement and step."""

import json
from pathlib import Path

from infrastructure.shared.models.text import TextModel
from infrastructure.stages.database.obligations.records import normalize_inference, normalize_obligations, check_symbols
from infrastructure.stages.database.schema import check_related_fields
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.formatting import format_schema
from infrastructure.utils.presentation.formatting import format_obligations
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.backend.evidence import load_evidence, scoped_evidence
from infrastructure.stages.requirements.data import load_data, data_context, DATA_INSTRUCTIONS
from infrastructure.utils.files import read_artifact
from infrastructure.utils.files import save_json
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.agent.tasks import TaskFailures
from infrastructure.shared.agent.discovery import ContextIndex


# --- Extension point 03A: obligation inference policy --------------------------
# Rewrite how requirement text maps to reads/writes, especially failure paths,
# fixture setup, and generated keys. Records are normalized for set operations.
INSTRUCTIONS = DATA_INSTRUCTIONS + """Infer this requirement's database reads and writes over the supplied related_schema.
Return:
{
  "requirement": {"read": ["Entity.field"], "write": ["Entity.field"], "observation_read": ["Entity.field"]},
  "steps": {"STEP-ID": {"read": ["Entity.field"], "write": ["Entity.field"], "observation_read": ["Entity.field"]}}
}
"read" and "write" are separate fields containing arrays of qualified DB field names.
Use [] when a set is empty. Include the supplied step IDs; use steps={} when there
are no steps. Select existing schema symbols; do not create schema definitions.

Use backend_evidence and backend_foundation alongside descriptions/scenarios. Include
source-required transition effects, reversals and all related inventory/ledger fields;
Automatic ownership creation, audit and command receipts are compiler infrastructure
and need not be charged as extra business writes. An explicitly required workflow
assignee change MUST include record_access.assignee_id as a domain effect. Login/me/logout use the fixed auth_sessions,
users, org_units and user_ou_roles contracts, not invented Session/Account synonyms.
Do not classify source-required effects as UI-only because their ER reference is indirect.
Infer requirement effects from its description and complete scenarios. Infer each
step's effects from its own Given/When/Then and requirement context. Keep these
records specific: do not copy the requirement's writes into every step. The leaf
requirement must cover the effects of all its own steps; it may also describe behavior
not exercised by a step. References provide context, not inherited effects.

Given fixtures describe existing state, not writes performed by the behavior under
test. This includes prerequisite actions described in Given, even when those actions
create records through the UI. Do not charge their writes to the current When action.
Rejection and instructions to leave data unchanged do not imply writes.
read describes data needed by the application behavior, not SQL used only by an acceptance
oracle to prove a Then invariant. Put acceptance-only inspections of unchanged records,
absence, audit counts or forbidden effects in observation_read. They remain test obligations
but do not require a business API/Trigger call. User-visible queries and actual guard inputs
remain read; do not reclassify a real business lookup merely to eliminate a coverage error.
Include lookup, filter and join keys in reads, and persisted generated keys in writes.
For source-defined derived/aggregate records, consider the first execution with no
existing aggregate row. If absence represents an initial zero/empty state, the operation
must be able to materialize that row: include its generated primary key, association
keys and required fields in possible writes. Do not assume a stock/balance/counter row
has been seeded merely because later operations update it. Keep this branch distinct
from Given fixtures and from a source-required missing-record rejection.
A field can occur in both arrays. Read/write sets describe possible behavior across
branches, not effects required on every invocation. Related fields are candidates;
there is no need to classify every supplied field. UI-only state has no DB effect.
For credentials, distinguish submitted passwords from stored hashes.
Reads describe necessary data capabilities, not an exhaustive SQL access whitelist.
Include persisted re-reads required by reload, navigation or reopening an editor;
returning data from a create operation does not replace a later retrieval operation.
"""


def infer_db_obligations(arc_dir: Path, pause: bool = False, top_k: int = 6, max_attempts: int = 10) -> dict:
    for filename, previous in (("requirements.json", "main.py --stage 01"), ("db_schema.json", "main.py --stage 02")):
        if not (arc_dir / filename).is_file():
            raise ValueError(f"Run {previous} first to create .arc/{filename}")
    if top_k < 1:
        raise ValueError("--top-k must be positive")
    tree = RequirementTree(json.loads((arc_dir / "requirements.json").read_text(encoding="utf-8-sig")))
    tree.validation_data = load_data(arc_dir)
    schema = json.loads((arc_dir / "db_schema.json").read_text(encoding="utf-8-sig"))
    evidence = load_evidence(arc_dir)
    foundation = read_artifact(arc_dir,"backend_foundation.json") if (arc_dir/"backend_foundation.json").is_file() else {"enabled":False}
    # --- Pass boundary: use the existing database symbol space ----------------
    # Inference may select existing fields, but cannot create schema symbols.
    # An unmapped concept should trigger schema review, not a fabricated field.
    console = DemoConsole(pause)
    model = TextModel()
    # Organizational parents keep empty records; only leaves receive model inference.
    obligations = {"requirements": {rid: {"read": [], "write": []} for rid in tree.requirements if tree.children[rid]},
        "steps": {sid: {"read": [], "write": []} for rid in tree.requirements if tree.children[rid] for sid in tree.own_steps[rid]}}

    failures = TaskFailures(arc_dir, "03_infer_db_obligations", console)
    save_json(arc_dir / "db_obligations.json", obligations)
    for index, rid in enumerate(tree.leaves, 1):
        with failures.task(rid):
            requirement = tree.requirements[rid]
            label = f"{index}/{len(tree.leaves)} {rid}"
            steps_text = tree.concatenated_steps(rid)
            console.show(f"{label} | 1. Current requirement and steps", (
                f"{requirement['name']}\n\nDescription:\n{requirement['description']}"
                f"\n\nConcatenated steps:\n{steps_text or '(No steps on this requirement.)'}"
            ))
            related_fields = schema["requirements"].get(rid)
            try:
                check_related_fields(schema, related_fields)
            except ValueError as error:
                raise ValueError(f"Invalid schema associations for {rid} in .arc/db_schema.json. "
                    f"Rerun main.py --stage 02 to repair the schema before inference. {error}") from error
            related_entities = {}
            for symbol in related_fields:
                entity, field = symbol.split(".", 1)
                related_entities.setdefault(entity, {"description": schema["entities"][entity]["description"], "fields": {}})
                related_entities[entity]["fields"][field] = schema["entities"][entity]["fields"][field]
            console.show(f"{label} | 2. Related schema fields", format_schema(related_entities))
            # --- Extension point 03C: inference granularity and feedback -----------
            # One call currently predicts a requirement and all its own steps.
            # Try separate calls or richer evidence, while retaining every node ID
            # and step-specific read/write sets. Report inconsistent inference
            # for model correction rather than silently expanding its records.
            request = {
                "requirement": requirement,
                "validation_data": data_context(tree.validation_data,rid),
                "backend_evidence": scoped_evidence(evidence,rid),
                "backend_foundation": foundation,
                "steps": [tree.steps[sid] for sid in tree.own_steps[rid]],
                "related_fields": sorted(related_fields),
                "related_schema": {"entities": related_entities},
            }
            def accept(response):
                inferred = normalize_inference(response, tree.own_steps[rid])
                check_symbols([inferred["requirement"], *inferred["steps"].values()], schema)
                summary = format_obligations({rid: inferred["requirement"], **inferred["steps"]})
                return inferred, summary

            (inferred, summary), _ = propose_json(model, INSTRUCTIONS, request, accept,
                console, f"Obligation inference {rid}", max_attempts, context_index=ContextIndex(lambda: {"schema": schema["entities"]}))
            obligations["requirements"][rid] = inferred["requirement"]
            obligations["steps"].update(inferred["steps"])
            save_json(arc_dir / "db_obligations.json", obligations)
            console.artifact("db_obligations", obligations, f"{label} | Accepted obligations")
            console.show(f"{label} | 4. Inferred obligations", summary)

    failures.finish()
    obligations = normalize_obligations(obligations, tree)
    save_json(arc_dir / "db_obligations.json", obligations)
    print(f"Obligations saved: {arc_dir / 'db_obligations.json'}", flush=True)
    return obligations
