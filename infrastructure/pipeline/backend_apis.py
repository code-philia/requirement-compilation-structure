"""Outline APIs in stage 05; prepare executable contracts inside implementation."""

from copy import deepcopy
import json
import os
from pathlib import Path

from infrastructure.stages.backend.context import load_context, requirement_context, api_requirement_uses
from infrastructure.stages.database.obligations.records import check_symbols, normalize_inference
from infrastructure.stages.backend.primitives import apply_decomposition, validate_design
from infrastructure.stages.backend.contracts import CONTRACT_INSTRUCTIONS, validate_backend_contracts, builtin_apis, validate_process_coverage, finalize_backend_contracts
from infrastructure.stages.backend.platform_files import publish_routes
from infrastructure.shared.models.text import TextModel
from infrastructure.stages.database.obligations.rules import union
from infrastructure.utils.presentation.formatting import format_apis
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.formatting import format_obligations
from infrastructure.shared.rag.apis import ApiRetriever
from infrastructure.utils.files import save_json
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.agent.tasks import TaskFailures
from infrastructure.shared.agent.discovery import ContextIndex
from infrastructure.shared.agent.conventions import CONVENTION_RULES, load_conventions, select_conventions, merge_conventions


INSTRUCTIONS = """Design complete backend APIs for the supplied leaf requirement and scenarios.
Design each operation's signature, input, output, DB reads, DB writes, preconditions
and postconditions together. Return {"apis": {"API-ID": {...}}, "requirement_apis": []}.
apis contains COMPLETE new or changed definitions; reuse unchanged APIs by ID only.
Each API has these separate top-level properties:
- description: the business operation.
- read: array of qualified DB fields read by the operation.
- write: array of qualified DB fields written by the operation.
- signature: {name: TypeScript function name, method: HTTP method, path: /api/...}.
- request: {params: JSON schema, query: JSON schema, body: JSON schema, headers: JSON schema}.
- response: {success: {status, body: JSON schema, headers: JSON schema},
  errors: [{status, body: JSON schema, headers: JSON schema}]}.
- precondition: [{id, description, error_status}], or [] for an unconditional operation.
- postcondition: [{id, description, status}], describing observable response and DB
  outcomes, including unchanged data on rejection when required.

Use inline JSON Schemas for I/O, with object properties/required and array items where
appropriate. Declare route parameters in params. Use lower-case header names and
state any shared credential/cookie convention consistently across related APIs.
Response bodies expose business results, not password hashes or session secrets.
Specify success and rejection branches supported by the requirement; HTTP 501 is
reserved for the TDD stub. Do not invent business policy or generic failure branches.

retrieved_apis contains selected canonical definitions, not the complete API inventory. The current requirement is separate. A shared API has one
canonical interface and P/Q covering its known uses. Return a complete updated API
when new evidence requires coordinated interface or P/Q changes; retain earlier behavior.

requirement_apis lists APIs directly needed by this requirement. The union of their
read arrays must cover its read obligation; supporting lookups, joins and extra response
fields are allowed. The union of write arrays must equal its write obligation. The
selected APIs must also cover each supplied step_obligations record. Shared API
updates must preserve coverage of earlier requirements. Effects can overlap across
APIs and describe possible effects across branches, not unconditional per-call access.
Design the operations needed at each point of the scenario. A create response is not
a reload endpoint: provide/reuse read operations for reload, direct entry, reopening
forms and post-mutation navigation. Include those read APIs in requirement_apis even
when a mutation API already reads the same fields. Do not use transient browser state
as a substitute for retrieving persisted data. Given setup is not a current API mutation.
Use requirement_apis=[] for requirements with no backend behavior and empty obligations.
Return only API definitions and requirement associations.
"""


def design_backend_apis(arc_dir: Path, pause: bool = False, top_k: int = 6, max_attempts: int = 10, *, joint_obligations=False, implementation_plan=None) -> dict:
    tree, schema, obligations = load_context(arc_dir, infer_obligations=joint_obligations)
    if top_k < 1:
        raise ValueError("--top-k must be positive")
    console, retriever, model = DemoConsole(pause), ApiRetriever(), TextModel()
    conventions = load_conventions(arc_dir)
    foundation = getattr(tree,"backend_foundation",{"enabled":False})
    evidence = getattr(tree,"backend_evidence",{})
    # Parents organize requirements; they do not receive APIs or coverage checks.
    design = {"apis": builtin_apis(schema) if foundation.get("enabled") else {}, "requirements": {rid: [] for rid in tree.requirements if tree.children[rid]}}
    if not joint_obligations and os.getenv("ARC_REUSE_ACCEPTED_BACKEND_APIS") == "1" and (arc_dir/"backend_apis.json").is_file():
        from infrastructure.utils.files import read_artifact
        existing = read_artifact(arc_dir,"backend_apis.json")
        if not set(existing["requirements"]) <= set(tree.requirements):
            raise ValueError("Cannot resume APIs for a different requirement tree")
        finalize_backend_contracts(existing,foundation)
        check_symbols(existing["apis"].values(),schema)
        validate_design(existing,obligations,complete=False,tree=tree)
        validate_backend_contracts(existing,foundation,evidence,schema)
        validate_process_coverage(existing,foundation,evidence)
        design = existing
        save_json(arc_dir/"backend_api_resume.json",{"validated_requirements":list(existing["requirements"]),"mode":"explicit_source_reviewed_resume"})
    # --- Extension point 05A: leaf order and reusable API discovery ------------
    failures = TaskFailures(arc_dir, "06_backend_contracts" if implementation_plan is not None else "05_design_backend_apis", console)
    save_json(arc_dir / "backend_apis.json", design)
    for number, rid in enumerate(tree.leaves, 1):
        if rid in design["requirements"]:
            console.show("Reuse validated API design "+rid,"Previously accepted contracts revalidated against current schema, obligations and foundation.")
            continue
        with failures.task(rid):
            context = requirement_context(tree, rid)
            required = obligations["requirements"][rid]
            step_obligations = {sid: obligations["steps"][sid] for sid in tree.own_steps[rid]}
            label = f"{number}/{len(tree.leaves)} {rid}"
            console.show(f"{label} | 1. Requirement and Dataflow Obligations", (
                context["name"] + "\n" + context["description"] + "\n\n" + tree.concatenated_steps(rid)
                + "\n\nRequirement obligations:\n" + format_obligations({rid: required})
            ))
            console.show(f"{label} | 2. All Existing APIs", format_apis(design["apis"]))
            query = json.dumps({"requirement": context, "obligations": required}, ensure_ascii=False)
            candidates = design["apis"]
            retrieved = retriever.retrieve(query, candidates, top_k)
            console.show(f"{label} | 3. Retrieved APIs (RAG)", (
                "\n".join(f"{item['symbol']} BM25={item['score']:.4f}" for item in retrieved["matches"])
                + "\n\n" + format_apis(retrieved["apis"])
            ))
            related = set(required["read"]) | set(required["write"])
            for effects in step_obligations.values():
                related.update(effects["read"])
                related.update(effects["write"])
            for api in retrieved["apis"].values():
                related.update(api["read"])
                related.update(api["write"])
            related_schema = {name: {"description": entity["description"],
                "fields": {field: value for field, value in entity["fields"].items() if f"{name}.{field}" in related}}
                for name, entity in schema["entities"].items()
                if any(symbol.startswith(name + ".") for symbol in related)}
            if joint_obligations:
                from infrastructure.stages.database.schema import check_related_fields
                source_fields = schema["requirements"].get(rid)
                check_related_fields(schema, source_fields)
                related.update(source_fields)
                # Complete definitions for source-associated tables plus FK dependencies,
                # not the entire system schema repeated for every requirement.
                names = {symbol.split(".", 1)[0] for symbol in related}
                pending = list(names)
                while pending:
                    for field in schema["entities"][pending.pop()]["fields"].values():
                        reference = field.get("references")
                        if reference and reference.split(".", 1)[0] not in names:
                            target = reference.split(".", 1)[0]
                            names.add(target)
                            pending.append(target)
                related_schema = {name: entity for name, entity in schema["entities"].items() if name in names}
                related = {f"{name}.{field}" for name, entity in related_schema.items() for field in entity["fields"]}
            request = {
                "requirement": context, "obligations": required, "step_obligations": step_obligations,
                "backend_foundation": foundation,
                "platform_apis": builtin_apis(schema) if foundation.get("enabled") else {},
                "related_schema": related_schema,
                "shared_conventions": select_conventions(conventions, fields=related, requirements=[rid]),
                "retrieved_apis": retrieved["apis"], "api_inventory": list(retrieved["apis"]),
            }
            if implementation_plan is not None:
                request["implementation_outline"] = {
                    "items": {aid: implementation_plan["items"][aid]
                        for aid in implementation_plan["requirements"][rid]},
                    "notes": implementation_plan["notes"][rid],
                    "policy": "Implement this outline; only add/revise operations when source evidence requires it. "
                              "Use minimal concrete I/O and conditions needed for executable routing and acceptance. "
                              "Do not elaborate implementation algorithms or duplicate business prose."}
            if joint_obligations:
                request.pop("obligations")
                request.pop("step_obligations")
            def accept(response):
                nonlocal conventions, obligations
                candidate_obligations = deepcopy(obligations)
                if joint_obligations:
                    inferred = normalize_inference(response["obligations"], tree.own_steps[rid])
                    check_symbols([inferred["requirement"], *inferred["steps"].values()], schema)
                    candidate_obligations["requirements"][rid] = inferred["requirement"]
                    candidate_obligations["steps"].update(inferred["steps"])
                updated = apply_decomposition(design, response, rid, candidate_obligations, tree=tree)
                finalize_backend_contracts(updated,foundation)
                check_symbols(updated["apis"].values(), schema)
                validate_backend_contracts(updated,foundation,evidence,schema)
                validate_process_coverage(updated,foundation,evidence)
                revised = merge_conventions(conventions, response, rid, related)
                selected = {aid: updated["apis"][aid] for aid in updated["requirements"][rid]}
                definitions = {aid: {key: api[key] for key in (
                    "signature", "request", "response", "read", "write", "precondition", "postcondition")}
                    for aid, api in selected.items()}
                console.show(f"{label} | Complete API definitions", json.dumps(definitions, ensure_ascii=False, indent=2))
                console.show(f"{label} | API design / Obligation Propagation",
                    format_apis(selected) + "\nRequired direct obligations:\n" + format_obligations({rid: required})
                    + "\nAssigned API obligation union:\n" + format_obligations({rid: union(selected.values())}))
                conventions = revised
                obligations = candidate_obligations
                return updated

            joint_rules = ""
            if joint_obligations:
                from infrastructure.pipeline.db_obligations import INSTRUCTIONS as EFFECT_RULES
                joint_rules = ("\nJoint output: return apis, requirement_apis, conventions (if needed), and obligations. "
                    "Retrieve additional schema definitions only for a specific missing source-required effect. "
                    "obligations contains {requirement:{read:[],write:[],observation_read:[]},steps:{STEP_ID:{read:[],write:[],observation_read:[]}}}. "
                    "Infer these independently from original scenarios, then design APIs satisfying them in this SAME response. "
                    "Never derive obligations merely by copying your API union or omit source behavior to make coverage pass. "
                    "The following effect rules apply ONLY inside obligations, not as the root response:\n" + EFFECT_RULES)
            updated, _ = propose_json(model, INSTRUCTIONS + joint_rules + "\n\n" + CONVENTION_RULES + (CONTRACT_INSTRUCTIONS if foundation.get("enabled") else ""), request, accept, console,
                f"Backend executable contract {rid}", max_attempts, context_index=ContextIndex(lambda: {"convention": conventions, "api": design["apis"], "schema": schema["entities"], "requirement": {key: requirement_context(tree, key) for key in tree.leaves}}))
            design = updated
            save_json(arc_dir / "backend_apis.json", design)
            if joint_obligations:
                save_json(arc_dir / "db_obligations.json", obligations)
            publish_routes(arc_dir.parent,design,foundation)
            save_json(arc_dir / "shared_conventions.json", conventions)
            console.artifact("backend_apis", design, f"{label} | Accepted APIs")
    publish_routes(arc_dir.parent,design,foundation)
    failures.finish()
    # --- Extension point 05B: API -> DB Access Primitive decomposition ---------
    # Intentionally absent: an API directly accesses the database in step 06.
    validate_design(design, obligations, tree=tree)
    validate_backend_contracts(design,foundation,evidence,schema)
    validate_process_coverage(design,foundation,evidence)
    publish_routes(arc_dir.parent,design,foundation)
    save_json(arc_dir / "backend_apis.json", design)
    if joint_obligations:
        save_json(arc_dir / "db_obligations.json", obligations)
    print(f"Backend API Primitives saved: {arc_dir / 'backend_apis.json'}", flush=True)
    return design


def design_backend_joint(arc_dir: Path, pause: bool = False) -> dict:
    """Declare approximate APIs and source locations, without detailed contracts."""
    from infrastructure.shared.agent.outlines import plan_requirements
    tree, schema, _ = load_context(arc_dir, infer_obligations=True)
    builtin = builtin_apis(schema) if tree.backend_foundation.get("enabled") else {}
    inventory = {aid: {"purpose": api["description"],
        "method": api["signature"]["method"], "path": api["signature"]["path"],
        "implementation_hint": "backend/src/platform/"} for aid, api in builtin.items()}
    return plan_requirements(arc_dir, 'backend', tree,
        {rid: requirement_context(tree, rid) for rid in tree.leaves}, inventory=inventory, pause=pause)


def prepare_backend_contracts(arc_dir, pause=False):
    """Implementation owns executable contracts required by the guarded HTTP runtime."""
    from infrastructure.shared.agent.outlines import load_outline, fingerprint
    from infrastructure.utils.files import read_artifact
    plan = load_outline(arc_dir, 'backend')
    marker = arc_dir / 'backend_contract_preparation.json'
    digest = fingerprint(plan)
    if marker.is_file() and all((arc_dir / name).is_file() for name in ('backend_apis.json', 'db_obligations.json')):
        previous = read_artifact(arc_dir, marker.name)
        if previous.get('status') == 'GREEN' and previous.get('plan_sha256') == digest:
            return
    save_json(marker, {'status': 'RUNNING', 'plan_sha256': digest})
    design_backend_apis(arc_dir, pause=pause, joint_obligations=True, implementation_plan=plan)
    save_json(marker, {'status': 'GREEN', 'plan_sha256': digest})
