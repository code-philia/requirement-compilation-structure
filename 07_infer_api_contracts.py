"""Step 07: infer P/Q conditions over fixed API interfaces and obligations."""

import json
from contextlib import ExitStack
from pathlib import Path

from infrastructure.stages.backend.context import load_context, api_requirement_uses
from infrastructure.utils.files import read_artifact
from infrastructure.stages.backend.contracts import validate_contracts, validate_registry
from infrastructure.stages.backend.primitives import validate_design
from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.shared.models.text import TextModel
from infrastructure.stages.database.obligations.records import field_symbols
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.presentation.formatting import format_apis
from infrastructure.utils.files import save_json
from infrastructure.shared.models.structure import object_fields


INSTRUCTIONS = """Perform Contract Inference for the selected Backend API Primitive:
API = <signature, I, O, R, W, P, Q>. Signature, I/O and R/W are fixed by step 06.
Infer ONLY precondition (P) and postcondition (Q), using ALL supplied requirement
uses and their success/failure steps. Do not invent business policy or new operations.
Return exactly {"contract": {...}}.
contract contains exactly:
- precondition: [{id, description, error_status}].
- postcondition: [{id, description, status}].
Use the supplied fixed request/response schemas; do not regenerate them.
Each response status must have at least one postcondition. Precondition error_status
must be a declared error status. IDs must be unique within this API (use P-/Q- prefixes).
Include invalid inputs and requirement-defined failures, preserving accounts and sessions
on rejection. Avoid returning password hashes or other credentials. Connect postconditions
to returned data AND required DB effects, including forbidden writes on failure.
Do not add generic infrastructure-error branches without requirement evidence. HTTP 501
is reserved for the temporary TDD stub and must not appear in the contract.
An empty precondition list is valid for an unconditional operation; postconditions are
not empty. Align shared session/cookie conventions with existing_contracts.
Use descriptions to state semantic rules. Do not return field pointers or explanation,
or repeat the API signature, request, response, description, read or write. A shared API gets one canonical contract covering all its uses.
If the fixed interface cannot express required behavior, report the mismatch rather
than inventing fields or statuses. If correction is supplied, change only P/Q.
"""


def infer_api_contracts(arc_dir: Path, pause: bool = False) -> dict:
    tree, schema, obligations = load_context(arc_dir)
    design = read_artifact(arc_dir, "backend_apis.json")
    validate_design(design, obligations, field_symbols(schema), tree=tree)
    result = {"apis": {}, "requirements": design["requirements"]}
    console, model = DemoConsole(pause), TextModel()
    # Each API has one canonical contract, inferred from all direct owners.
    for aid, selected in design["apis"].items():
        uses = api_requirement_uses(tree, design["requirements"], aid)
        console.show(f"{aid} | 1. Shared requirement uses / fixed API", (
            json.dumps(uses, ensure_ascii=False, indent=2)
            + "\n\n" + format_apis({aid: selected})
        ))
        related = set(selected["read"]) | set(selected["write"])
        related_schema = {name: {"description": entity["description"],
            "fields": {field: value for field, value in entity["fields"].items() if f"{name}.{field}" in related}}
            for name, entity in schema["entities"].items()
            if any(symbol.startswith(name + ".") for symbol in related)}
        request = {"api_id": aid, "api": selected, "all_requirement_uses": uses,
            "related_schema": related_schema, "existing_contracts": result["apis"]}
        for attempt in range(1, 4):
            response = None
            try:
                response = model.generate_json(INSTRUCTIONS, request)
                object_fields(response, {"contract": dict}, "contract response")
                contract = object_fields(response["contract"], {"precondition": list, "postcondition": list}, "contract")
                api = {**selected, "precondition": contract["precondition"], "postcondition": contract["postcondition"]}
                validate_registry({**result["apis"], aid: api})
                break
            except ValueError as error:
                if attempt == 3:
                    raise ValueError(f"Contract Inference failed for {aid}: {error}") from error
                print(f"Retrying {aid} ({attempt + 1}/3): {error}", flush=True)
                request["correction"] = {"error": str(error), "previous_response": response}
        result["apis"][aid] = api
        console.show(f"{aid} | 2. Accepted precondition (P) / postcondition (Q)",
            json.dumps({key: api[key] for key in ("precondition", "postcondition")}, ensure_ascii=False, indent=2))
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
