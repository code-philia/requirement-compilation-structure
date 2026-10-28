"""Step 07: Contract Inference for Backend API Primitives."""

import json
from contextlib import ExitStack
from pathlib import Path

from infrastructure.stages.backend.context import load_context, requirement_context
from infrastructure.utils.files import read_artifact
from infrastructure.stages.backend.contracts import validate_contract, validate_contracts, validate_registry
from infrastructure.stages.backend.primitives import validate_design
from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.shared.models.text import TextModel
from infrastructure.stages.database.obligations.records import field_symbols
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.presentation.formatting import format_apis
from infrastructure.utils.files import save_json


INSTRUCTIONS = """Perform Contract Inference for the selected Backend API Primitive:
API = <signature, I, O, R, W, P, Q>. R/W are fixed. Infer signature, request (I),
response (O), precondition (P), and postcondition (Q), using ALL supplied requirement
uses and their success/failure steps. Do not invent business policy or new operations.
Return exactly {"contract": {...}, "explanation": "..."}.
contract contains exactly:
- signature: {name: TypeScript function identifier, method: GET|POST|PUT|PATCH|DELETE,
  path: /api/... with optional :named parameters}. /api/health is reserved.
- request: {params: schema, query: schema, body: schema, headers: schema}.
- response: {success: {status: 2xx, body: schema, headers: schema},
  errors: [{status: 4xx/5xx, body: schema, headers: schema}]}.
- precondition: [{id, description, request_fields: [JSON pointers], error_status}].
- postcondition: [{id, description, response_fields: [JSON pointers], status}].
Use inline JSON Schemas with explicit type (object,array,string,integer,number,boolean,
null). Objects declare properties and required; arrays declare items. No $ref, unions,
or custom keywords. Empty object: {type:"object",properties:{},required:[]}.
Supported constraints: enum,const,minLength,maxLength,minimum,maximum,pattern,format,
minItems,maxItems,additionalProperties(boolean). Headers use lower-case names.
Request params/query/body/headers and response headers are object schemas.
Every :parameter must be declared and required in params. Request field pointers look
like /body/username or /headers/cookie. Postcondition pointers look like /body/user,
/headers/set-cookie, or /status. Each condition must bind at least one declared field.
Each response status must have at least one postcondition. Precondition error_status
must be a declared error status. IDs must be unique within this API (use P-/Q- prefixes).
Include invalid inputs and requirement-defined failures, preserving accounts and sessions
on rejection. Avoid returning password hashes or other credentials. Connect postconditions
to returned data AND required DB effects, including forbidden writes on failure.
Do not add generic infrastructure-error branches without requirement evidence. HTTP 501
is reserved for the temporary TDD stub and must not appear in the contract.
An empty precondition list is valid for an unconditional operation; postconditions are
not empty. Align shared session/cookie conventions with existing_contracts. Explain
signature, request, response, P and Q separately. A shared API gets one canonical contract
covering all its uses. If correction is supplied, fix it without changing R or W.
"""


def infer_api_contracts(arc_dir: Path, pause: bool = False) -> dict:
    tree, schema, obligations, _ = load_context(arc_dir)
    design = read_artifact(arc_dir, "backend_apis.json")
    validate_design(design, obligations, field_symbols(schema), tree=tree)
    result = {"apis": {}, "requirements": design["requirements"]}
    console, model = DemoConsole(pause), TextModel()
    for rid, ids in design["requirements"].items():
        if not ids:
            console.show(f"{rid} | No direct API contracts", "Child APIs are not inherited; this requirement has no direct API Primitive to infer.")
            continue
        for aid in ids:
            label = f"{rid} / {aid}"
            uses = [requirement_context(tree, key) for key, bindings in design["requirements"].items() if aid in bindings]
            console.show(f"{label} | 1. Requirement / API Primitive", (
                json.dumps(requirement_context(tree, rid), ensure_ascii=False, indent=2)
                + "\n\n" + format_apis({aid: design["apis"][aid]})
            ))
            console.show(f"{label} | 2. Shared API uses / existing signatures", (
                "Requirement uses: " + ", ".join(item["id"] for item in uses)
                + "\nExisting signatures:\n" + json.dumps({key: api["signature"] for key, api in result["apis"].items()}, indent=2)
            ))
            # --- Extension point 07A: inference granularity -------------------
            # Shared APIs are inferred once using every owning requirement.
            # Later bindings reuse the canonical contract rather than fork it.
            if aid in result["apis"]:
                api = result["apis"][aid]
                explanation = "Reused the canonical contract already inferred for all requirement uses."
            else:
                request = {"api_id": aid, "api": design["apis"][aid], "requirement": requirement_context(tree, rid), "all_requirement_uses": uses, "db_schema": schema, "existing_contracts": result["apis"]}
                for attempt in range(1, 4):
                    response = None
                    try:
                        response = model.generate_json(INSTRUCTIONS, request)
                        if not isinstance(response, dict) or set(response) != {"contract", "explanation"} or not isinstance(response["explanation"], str):
                            raise ValueError("Return contract and explanation")
                        validate_contract(response["contract"])
                        api = {**design["apis"][aid], **response["contract"]}
                        validate_registry({**result["apis"], aid: api})
                        explanation = response["explanation"]
                        break
                    except ValueError as error:
                        if attempt == 3:
                            raise ValueError(f"Contract Inference failed for {aid}: {error}") from error
                        print(f"Retrying {aid} ({attempt + 1}/3): {error}", flush=True)
                        request["correction"] = {"error": str(error), "previous_response": response}
                result["apis"][aid] = api
            console.show(f"{label} | 3. Signature / Request (I) / Response (O)", json.dumps({key: api[key] for key in ("signature", "request", "response")}, ensure_ascii=False, indent=2))
            console.show(f"{label} | 4. Precondition (P) / Postcondition (Q)", (
                explanation + "\n\n" + json.dumps({key: api[key] for key in ("precondition", "postcondition")}, ensure_ascii=False, indent=2)
            ))
    validate_contracts(result, design)
    save_json(arc_dir / "backend_contracts.json", result)
    print(f"Backend API contracts saved: {arc_dir / 'backend_contracts.json'}", flush=True)
    return result


def main() -> None:
    parser = create_parser("Step 07: Backend API Contract Inference")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output = resolve_directories(args)
            stack.enter_context(console_log(output))
            infer_api_contracts(output / ".arc", args.pause)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
