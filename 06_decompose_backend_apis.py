"""Step 06: Backend API Decomposition and Obligation Propagation."""

import json
from contextlib import ExitStack
from pathlib import Path

from infrastructure.stages.backend.context import load_context, requirement_context
from infrastructure.stages.backend.primitives import ObligationCoverageError, apply_decomposition, descendant_apis, requirement_scope, validate_design
from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.shared.models.text import TextModel
from infrastructure.stages.database.obligations.records import field_symbols
from infrastructure.stages.database.obligations.rules import union
from infrastructure.utils.presentation.formatting import format_apis
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.presentation.formatting import format_obligations
from infrastructure.shared.rag.apis import ApiRetriever
from infrastructure.utils.files import save_json


INSTRUCTIONS = """Perform Backend API Decomposition and Obligation Propagation only.
Return exactly {"apis": {"API-ID": {"description": "Business operation", "read": [],
"write": []}}, "requirement_apis": ["API-ID"], "explanation": "Reuse and allocation evidence"}.
apis contains new or updated complete definitions; omit unchanged reused definitions.
IDs use letters, numbers, underscores or hyphens, starting with a letter. Reuse retrieved
APIs before creating another operation with the same semantics. One requirement may
need multiple APIs. Preserve established API identities and earlier allocations.
Separate READ and WRITE obligations. Assigned APIs must cover the supplied DIRECT
obligations. Never inherit, bind, wrap, or redesign descendant APIs at a parent node.
For each mode X in {read, write}, required[X] must be a subset of the UNION of
assigned APIs' X obligations. If correction contains missing fields, revise the
allocation or API definitions to cover them and return the complete proposal again.
Preserve legitimate business behavior and all previously validated allocations.
Child requirements already cover their own behavior and obligations through the subtree.
For leaves, assigned API unions equal the requirement's full read/write obligations.
For parents, implement only their own steps and responsibilities missing from child
coverage. Supporting reads may use allowed_obligations.read, including shared keys;
writes must equal the direct write obligation, never duplicate inherited child writes.
The compiler separately checks total coverage by children plus directly assigned APIs.
Do not omit fields or assign the full requirement obligation to every API.
Use exact schema symbols.
Sets may overlap: include a key in every API that reads it for a lookup or join;
obligation allocation is not a disjoint partition.
An API's write set describes possible successful effects, not a promise to write on
every invocation: failure paths can write nothing. Read-only operations have write=[].
Do not invent an endpoint solely to cover a field: every API needs business evidence.
For a parent, add an operation only for its own evidenced behavior (e.g. restoring a
session on refresh); child operations are context, not APIs to associate with the parent.
Return requirement_apis=[] when no backend behavior is needed and obligations are empty.
Do not infer signature, request, response, precondition or postcondition in this pass.
Each API may directly implement its business operation with database access.
Further decomposition into DB Access Primitives is an extension point, not this task.
If correction is supplied, fix the error and return one complete JSON object.
"""


def decompose_backend_apis(arc_dir: Path, pause: bool = False, top_k: int = 6) -> dict:
    tree, schema, obligations, todos = load_context(arc_dir)
    if top_k < 1:
        raise ValueError("--top-k must be positive")
    console, retriever, model = DemoConsole(pause), ApiRetriever(), TextModel()
    design = {"apis": {}, "requirements": {}}
    # --- Extension point 06A: visit order and reusable API discovery -----------
    # Validate parent aggregate coverage after allocating their leaves' APIs.
    number = 0
    for rid in tree.postorder:
        if tree.children[rid]:
            design["requirements"][rid] = []
            validate_design(design, obligations, field_symbols(schema), complete=False, tree=tree)
            console.show(f"{rid} | Skip non-leaf API analysis", "Only leaf requirements are analyzed. Parent obligation coverage is supplied by children; no direct API is assigned.")
            continue
        number += 1
        context = requirement_context(tree, rid)
        scope = requirement_scope(tree, obligations, rid)
        required = scope["required"]
        excluded = descendant_apis(tree, design, rid)
        label = f"{number}/{len(tree.leaves)} {rid}"
        console.show(f"{label} | 1. Requirement and Dataflow Obligations", (
            context["name"] + "\n" + context["description"] + "\n\n" + context["concatenated_steps"]
            + "\n\nAggregate obligations:\n" + format_obligations({rid: obligations["requirements"][rid]})
            + "\nAlready covered by children:\n" + format_obligations({rid: scope["children"]})
            + "\nDirect obligations for this node:\n" + format_obligations({rid: required})
        ))
        console.show(f"{label} | 2. All Existing APIs", format_apis(design["apis"]))
        query = json.dumps({"requirement": context, "obligations": required}, ensure_ascii=False)
        candidates = {aid: api for aid, api in design["apis"].items() if aid not in excluded}
        retrieved = retriever.retrieve(query, candidates, top_k)
        console.show(f"{label} | 3. Retrieved APIs (RAG)", (
            "\n".join(f"{item['symbol']} BM25={item['score']:.4f}" for item in retrieved["matches"])
            + "\nExcluded descendant APIs: " + (", ".join(sorted(excluded)) or "(none)")
            + "\n\n" + format_apis(retrieved["apis"])
        ))
        request = {
            "requirement": context, "obligations": required, "db_schema": schema,
            "allowed_obligations": scope["allowed"], "child_coverage": scope["children"],
            "retrieved_apis": retrieved["apis"], "api_inventory": list(candidates),
            "excluded_descendant_apis": sorted(excluded),
            "children": {cid: {"requirement": requirement_context(tree, cid), "obligations": obligations["requirements"][cid]} for cid in tree.children[rid]},
            "upstream_todos": [todo for todo in todos if todo["requirement"] == rid],
        }
        for attempt in range(1, 4):
            response = None
            console.show(f"{label} | 4. API Decomposition: attempt {attempt}/3", "Generate API Primitives, then check the union of their READ and WRITE obligations.")
            try:
                response = model.generate_json(INSTRUCTIONS, request)
                updated = apply_decomposition(design, response, rid, retrieved["apis"], obligations, field_symbols(schema), tree=tree)
                break
            except ValueError as error:
                correction = {"error": str(error), "previous_response": response}
                if isinstance(error, ObligationCoverageError):
                    correction["obligation_coverage"] = error.feedback
                console.show(f"{label} | Obligation validation failed ({attempt}/3)", json.dumps(correction, ensure_ascii=False, indent=2))
                if attempt == 3:
                    raise ValueError(f"Backend API Decomposition failed for {rid} after 3 attempts: {error}") from error
                print(f"Retrying {rid} ({attempt + 1}/3): {error}", flush=True)
                request["correction"] = correction
        selected = {aid: updated["apis"][aid] for aid in updated["requirements"][rid]}
        console.show(f"{label} | 4. API Decomposition / Obligation Propagation", (
            response["explanation"] + "\n\n" + format_apis(selected)
            + "\nRequired direct obligations:\n" + format_obligations({rid: required})
            + "\nAssigned API obligation union:\n" + format_obligations({rid: union(selected.values())})
            + "\nDirect API coverage passed; child coverage is accounted for separately."
        ))
        design = updated
    # --- Extension point 06B: API -> DB Access Primitive decomposition ---------
    # Intentionally absent: an API directly accesses the database in step 08.
    validate_design(design, obligations, field_symbols(schema), tree=tree)
    save_json(arc_dir / "backend_apis.json", design)
    print(f"Backend API Primitives saved: {arc_dir / 'backend_apis.json'}", flush=True)
    return design


def main() -> None:
    parser = create_parser("Step 06: Backend API Decomposition / Obligation Propagation")
    parser.add_argument("--top-k", type=int, default=6, help="Number of API retrieval hits")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output = resolve_directories(args)
            stack.enter_context(console_log(output))
            decompose_backend_apis(output / ".arc", args.pause, args.top_k)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
