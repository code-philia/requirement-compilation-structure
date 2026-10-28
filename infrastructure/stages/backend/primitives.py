"""API Primitive validation and requirement-to-API obligation conservation."""

from copy import deepcopy
import re

from infrastructure.stages.database.obligations.records import validate_record
from infrastructure.stages.database.obligations.rules import difference, union
from infrastructure.stages.backend.contracts import INTERFACE_KEYS, validate_registry

API_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")


class ObligationCoverageError(ValueError):
    """Structured feedback for the next API decomposition attempt."""

    def __init__(self, rid: str, required: dict, combined: dict, gaps: dict) -> None:
        """Carry the requirement, required obligations, API union, and uncovered fields into model correction feedback."""
        self.feedback = {
            "requirement_id": rid,
            "required_obligations": required,
            "api_obligation_union": combined,
            **gaps,
        }
        super().__init__(f"Obligation Propagation failed for {rid}: {self.feedback}")


def coverage(required: dict, apis: list[dict]) -> dict:
    """Return missing and excess read/write fields relative to the selected API obligation union."""
    combined = union(apis)
    return {"missing": difference(required, combined), "excess": difference(combined, required)}


def validate_design(design: dict, obligations: dict, symbols: set[str], complete: bool = True, tree=None) -> None:
    """Validate API definitions, requirement ownership, symbol references, and decomposition coverage."""
    if not isinstance(design, dict) or set(design) != {"apis", "requirements"}:
        raise ValueError("API design must contain apis and requirements")
    if not isinstance(design["apis"], dict) or not isinstance(design["requirements"], dict):
        raise ValueError("API definitions and requirement bindings must be objects")
    if complete and set(design["requirements"]) != set(obligations["requirements"]):
        raise ValueError("API bindings must include every requirement")
    names = set()
    for aid, api in design["apis"].items():
        if not API_ID.fullmatch(aid) or aid.lower() in names:
            raise ValueError(f"Invalid or duplicate API identity: {aid}")
        names.add(aid.lower())
        if not isinstance(api, dict) or set(api) != {"description", "read", "write"} | INTERFACE_KEYS:
            raise ValueError(f"API Primitive {aid} needs description, read, write, signature, request, response")
        if not isinstance(api["description"], str) or not api["description"].strip():
            raise ValueError(f"API description is required: {aid}")
        validate_record({key: api[key] for key in ("read", "write")}, symbols, aid)
    validate_registry(design["apis"], conditions=False)
    for rid, ids in design["requirements"].items():
        if rid not in obligations["requirements"] or not isinstance(ids, list) or any(not isinstance(aid, str) for aid in ids):
            raise ValueError(f"Invalid requirement/API binding: {rid}")
        if len(ids) != len(set(ids)) or set(ids) - set(design["apis"]):
            raise ValueError(f"Duplicate or unknown API binding: {rid}")
        # Organizational parents have no API allocation and no coverage check.
        # Leaf requirements are checked against their own inferred obligations,
        # independently of child/step obligation sets.
        if tree is not None and tree.children[rid]:
            if ids:
                raise ValueError(f"Parent {rid} must not bind APIs; only leaf requirements own API allocations")
            continue
        assigned = [design["apis"][aid] for aid in ids]
        combined = union(assigned)
        required = obligations["requirements"][rid]
        report = coverage(required, assigned)
        if any(fields for gap in report.values() for fields in gap.values()):
            raise ObligationCoverageError(rid, required, combined, report)
    used = {aid for ids in design["requirements"].values() for aid in ids}
    if set(design["apis"]) - used:
        raise ValueError("Unbound API Primitives are not allowed")


def apply_decomposition(design: dict, response: dict, rid: str, retrieved: dict, obligations: dict, symbols: set[str], tree=None) -> dict:
    """Apply one requirement's retrieved-API reuse and new API proposal to a copy, then validate before returning it."""
    if not isinstance(response, dict) or set(response) != {"apis", "requirement_apis", "explanation"}:
        raise ValueError("Decomposition must contain apis, requirement_apis, and explanation")
    if not isinstance(response["apis"], dict) or not isinstance(response["explanation"], str):
        raise ValueError("Invalid decomposition proposal")
    result = deepcopy(design)
    for aid, api in response["apis"].items():
        if aid in design["apis"] and aid not in retrieved:
            raise ValueError(f"Retrieve an existing API before updating it: {aid}")
        result["apis"][aid] = deepcopy(api)
    ids = response["requirement_apis"]
    if not isinstance(ids, list) or any(not isinstance(aid, str) for aid in ids):
        raise ValueError("requirement_apis must be an array of API IDs")
    if any(aid not in retrieved and aid not in response["apis"] for aid in ids):
        raise ValueError("Use only retrieved or newly proposed APIs")
    result["requirements"][rid] = ids
    # Recheck every earlier binding: changing a reused API must not silently
    # invalidate obligations already assigned to another requirement.
    validate_design(result, obligations, symbols, complete=False, tree=tree)
    return result
