"""Step 06: decompose APIs, allocate obligations, and design fixed I/O interfaces."""

import json
from pathlib import Path

from infrastructure.stages.backend.context import load_context, requirement_context
from infrastructure.stages.backend.primitives import ObligationCoverageError, apply_decomposition, validate_design
from infrastructure.shared.models.text import TextModel
from infrastructure.stages.database.obligations.records import field_symbols
from infrastructure.stages.database.obligations.rules import union
from infrastructure.utils.presentation.formatting import format_apis
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.formatting import format_obligations
from infrastructure.shared.rag.apis import ApiRetriever
from infrastructure.utils.files import save_json


INSTRUCTIONS = """Decompose backend APIs, allocate database obligations, then design their interfaces.
Analyze the requirement's operations first, select reusable APIs and allocate R/W,
then derive request/response and HTTP signatures from the related schema and effects.
Return only the final proposal and a concise explanation of these design decisions;
do not return intermediate reasoning or duplicate planning records.
Return exactly {"apis": {"API-ID": {"description": "Business operation", "read": [],
"write": [], "signature": {...}, "request": {...}, "response": {...}}},
"requirement_apis": ["API-ID"], "explanation": "Reuse, allocation and interface evidence"}.
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
Only leaf requirements are analyzed. Assigned API unions must equal the current
requirement's inferred read/write obligations. Parent and step obligations are not
compared with this requirement, and no inherited coverage is supplied.
Do not omit fields or assign the full requirement obligation to every API.
Use exact schema symbols.
Sets may overlap: include a key in every API that reads it for a lookup or join;
obligation allocation is not a disjoint partition.
An API's write set describes possible successful effects, not a promise to write on
every invocation: failure paths can write nothing. Read-only operations have write=[].
Do not invent an endpoint solely to cover a field: every API needs business evidence.
Return requirement_apis=[] when no backend behavior is needed and obligations are empty.
Each API includes:
- signature: {name: TypeScript function identifier, method: GET|POST|PUT|PATCH|DELETE,
  path: /api/... with optional :named parameters}. /api/health is reserved.
- request: {params: schema, query: schema, body: schema, headers: schema}.
- response: {success: {status: 2xx, body: schema, headers: schema},
  errors: [{status: 4xx/5xx, body: schema, headers: schema}]}.
Use inline JSON Schemas with explicit type: object,array,string,integer,number,boolean,null.
Objects declare properties and required; arrays declare items. Empty object schema:
{"type":"object","properties":{},"required":[]}. No $ref, unions or custom keywords.
Supported constraints: enum,const,minLength,maxLength,minimum,maximum,pattern,format,
minItems,maxItems,additionalProperties(boolean). Headers use lower-case names.
Request sections and response headers are object schemas. Every route parameter must
be declared and required in params. Function names and method/path routes must be unique.
Include requirement-defined success and rejection statuses; never use 501 or invent
generic infrastructure failures. Do not expose password hashes or session secrets in
response bodies. Preserve shared credential/header conventions across existing APIs.
Describe any shared cookie/token name explicitly in the header schema description so
producers and consumers share one convention. Never copy every DB field into I/O:
generated IDs/hashes can be server-owned, and UI-only confirmation can be request-only.
Do not return precondition or postcondition; step 07 adds those to the fixed interface.
Each API may directly implement its business operation with database access.
Further decomposition into DB Access Primitives is an extension point, not this task.
If correction is supplied, fix the error and return one complete JSON object.
"""


def decompose_backend_apis(arc_dir: Path, pause: bool = False, top_k: int = 6) -> dict:
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
        related_schema = {name: {"description": entity["description"],
            "fields": {field: value for field, value in entity["fields"].items() if f"{name}.{field}" in related}}
            for name, entity in schema["entities"].items()
            if any(symbol.startswith(name + ".") for symbol in related)}
        request = {
            "requirement": context, "obligations": required, "related_schema": related_schema,
            "retrieved_apis": retrieved["apis"], "api_inventory": list(candidates),
        }
        for attempt in range(1, 4):
            response = None
            console.show(f"{label} | 4. API Decomposition: attempt {attempt}/3", "Decompose operations, allocate R/W, and design signature/request/response; validate coverage and interfaces.")
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
        console.show(f"{label} | API interfaces", json.dumps({aid: {key: api[key]
            for key in ("signature", "request", "response")} for aid, api in selected.items()}, ensure_ascii=False, indent=2))
        console.show(f"{label} | 4. API Decomposition / Obligation Propagation", (
            response.get("explanation", "") + "\n\n" + format_apis(selected)
            + "\nRequired direct obligations:\n" + format_obligations({rid: required})
            + "\nAssigned API obligation union:\n" + format_obligations({rid: union(selected.values())})
            + "\nAPI obligation coverage passed."
        ))
        design = updated
    # --- Extension point 06B: API -> DB Access Primitive decomposition ---------
    # Intentionally absent: an API directly accesses the database in step 08.
    validate_design(design, obligations, field_symbols(schema), tree=tree)
    save_json(arc_dir / "backend_apis.json", design)
    print(f"Backend API Primitives saved: {arc_dir / 'backend_apis.json'}", flush=True)
    return design
