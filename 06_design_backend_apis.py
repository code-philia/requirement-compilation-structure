"""Step 06: design complete APIs with interfaces, obligations and P/Q."""

import json
from contextlib import ExitStack
from pathlib import Path

from infrastructure.stages.backend.context import load_context, requirement_context, api_requirement_uses
from infrastructure.stages.backend.primitives import ObligationCoverageError, apply_decomposition, validate_design
from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.shared.models.text import TextModel
from infrastructure.stages.database.obligations.rules import union
from infrastructure.utils.presentation.formatting import format_apis
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.presentation.formatting import format_obligations
from infrastructure.shared.rag.apis import ApiRetriever
from infrastructure.utils.files import save_json


INSTRUCTIONS = """Design complete backend APIs for the current requirement in one proposal.
Each API is <signature, I, O, R, W, P, Q>. Design its interface, database effects,
preconditions and postconditions together, using requirement success/failure scenarios.
Return {"apis": {"API-ID": {...}}, "requirement_apis": ["API-ID"]}.
apis contains complete new or changed API records; unchanged APIs are reused by ID.
Each API contains:
- description: the business operation.
- read/write: qualified database field symbols, compared independently.
- signature: {name: TypeScript function name, method: HTTP method, path: /api/...}.
- request: {params: JSON schema, query: JSON schema, body: JSON schema, headers: JSON schema}.
- response: {success: {status, body: JSON schema, headers: JSON schema},
  errors: [{status, body: JSON schema, headers: JSON schema}]}.
- precondition: [{id, description, error_status}]. It may be empty.
- postcondition: [{id, description, status}]. Describe observable results, response
  branches, DB effects and forbidden writes on rejection.
Use ordinary inline JSON Schemas for I/O. Declare route parameters in params.
Headers use lower-case names. Describe shared cookie/token conventions so related
APIs use the same convention. Keep secrets/hashes out of response bodies and do not
invent business rules or infrastructure failure branches. HTTP 501 is the TDD stub.

Reuse existing APIs when their operation matches. retrieved_apis includes complete
API definitions; api_uses supplies their previously associated requirements/scenarios.
The current requirement is supplied separately. A shared API has one canonical
interface and P/Q covering all known uses. If the current requirement adds behavior,
return its COMPLETE updated API, coordinating I/O and P/Q in the same proposal.
Preserve earlier behavior and API identities. No application code is implemented yet.

requirement_apis lists APIs directly needed by this leaf. For each read/write mode,
the allocated API union must equal the supplied requirement obligations. Updates to
shared APIs must also preserve coverage of previously analyzed requirements. Sets
may overlap across APIs; allocation is not a disjoint partition. DB writes describe
possible effects, not writes required on every invocation. Rejections may write nothing.
Every API needs business evidence; do not invent an operation merely to cover a field.
Use requirement_apis=[] when there is no backend behavior and obligations are empty.
Do not return code, tests, separate contract records or intermediate planning records.
If correction is supplied, return one complete corrected proposal.
"""


def design_backend_apis(arc_dir: Path, pause: bool = False, top_k: int = 6) -> dict:
    tree, schema, obligations = load_context(arc_dir)
    if top_k < 1:
        raise ValueError("--top-k must be positive")
    console, retriever, model = DemoConsole(pause), ApiRetriever(), TextModel()
    # Parents organize requirements; they do not receive APIs or coverage checks.
    design = {"apis": {}, "requirements": {rid: [] for rid in tree.requirements if tree.children[rid]}}
    # --- Extension point 06A: leaf order and reusable API discovery ------------
    for number, rid in enumerate(tree.leaves, 1):
        context = requirement_context(tree, rid)
        required = obligations["requirements"][rid]
        label = f"{number}/{len(tree.leaves)} {rid}"
        console.show(f"{label} | 1. Requirement and Dataflow Obligations", (
            context["name"] + "\n" + context["description"] + "\n\n" + context["concatenated_steps"]
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
        for api in retrieved["apis"].values():
            related.update(api["read"])
            related.update(api["write"])
        related_schema = {name: {"description": entity["description"],
            "fields": {field: value for field, value in entity["fields"].items() if f"{name}.{field}" in related}}
            for name, entity in schema["entities"].items()
            if any(symbol.startswith(name + ".") for symbol in related)}
        request = {
            "requirement": context, "obligations": required, "related_schema": related_schema,
            "retrieved_apis": retrieved["apis"], "api_inventory": list(candidates),
            "api_uses": {aid: api_requirement_uses(tree, design["requirements"], aid)
                for aid in retrieved["apis"]},
        }
        for attempt in range(1, 4):
            response = None
            console.show(f"{label} | 4. Complete API design: attempt {attempt}/3", "Design signature, I/O, R/W and P/Q together; check requirement-to-API DB coverage.")
            try:
                response = model.generate_json(INSTRUCTIONS, request)
                updated = apply_decomposition(design, response, rid, obligations, tree=tree)
                break
            except (json.JSONDecodeError, ObligationCoverageError) as error:
                correction = {"error": str(error), "previous_response": response}
                if isinstance(error, ObligationCoverageError):
                    correction["obligation_coverage"] = error.feedback
                else:
                    correction["invalid_response"] = error.doc
                console.show(f"{label} | Obligation validation failed ({attempt}/3)", json.dumps(correction, ensure_ascii=False, indent=2))
                if attempt == 3:
                    raise ValueError(f"Backend API design failed for {rid} after 3 attempts: {error}") from error
                print(f"Retrying {rid} ({attempt + 1}/3): {error}", flush=True)
                request["correction"] = correction
        selected = {aid: updated["apis"][aid] for aid in updated["requirements"][rid]}
        console.show(f"{label} | Complete API definitions", json.dumps({aid: {key: api[key]
            for key in ("signature", "request", "response", "read", "write", "precondition", "postcondition")} for aid, api in selected.items()}, ensure_ascii=False, indent=2))
        console.show(f"{label} | 4. API Decomposition / Obligation Propagation", (
            format_apis(selected)
            + "\nRequired direct obligations:\n" + format_obligations({rid: required})
            + "\nAssigned API obligation union:\n" + format_obligations({rid: union(selected.values())})
            + "\nAPI obligation coverage passed."
        ))
        design = updated
        console.artifact("backend_apis", design, f"{label} | Accepted APIs")
    # --- Extension point 06B: API -> DB Access Primitive decomposition ---------
    # Intentionally absent: an API directly accesses the database in step 08.
    validate_design(design, obligations, tree=tree)
    save_json(arc_dir / "backend_apis.json", design)
    print(f"Backend API Primitives saved: {arc_dir / 'backend_apis.json'}", flush=True)
    return design


def main() -> None:
    parser = create_parser("Step 06: Complete Backend API Design / Obligation Propagation")
    parser.add_argument("--top-k", type=int, default=6, help="Number of API retrieval hits")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output = resolve_directories(args)
            stack.enter_context(console_log(output, debug_model_io=args.debug_model_io))
            design_backend_apis(output / ".arc", args.pause, args.top_k)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
