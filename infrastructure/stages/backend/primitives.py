"""API Primitive validation and requirement-to-API obligation conservation."""

from copy import deepcopy
import re

from infrastructure.stages.database.obligations.records import validate_record
from infrastructure.stages.database.obligations.rules import difference, union

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


def requirement_scope(tree, obligations: dict, rid: str) -> dict:
    """Separate a node's direct responsibilities from its subtree aggregation."""
    total = obligations["requirements"][rid]
    children = union(obligations["requirements"][cid] for cid in tree.children[rid])
    steps = union(obligations["steps"][sid] for sid in tree.own_steps[rid])
    if any(difference(union([children, steps]), total).values()):
        raise ValueError(f"Checked obligations are not upward-complete at {rid}; rerun step 04")
    required = union([difference(total, children), steps])
    # A parent's own operation may read shared keys already used by children.
    # Child writes are not inherited as permission for another parent operation.
    allowed = {"read": total["read"], "write": required["write"]}
    return {"required": required, "allowed": allowed, "children": children}


def descendant_apis(tree, design: dict, rid: str) -> set[str]:
    """Collect APIs owned by descendant requirements for context without assigning them to the parent."""
    result = set()
    for child in tree.children[rid]:
        result.update(design["requirements"].get(child, []))
        result.update(descendant_apis(tree, design, child))
    return result


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
        if not isinstance(api, dict) or set(api) != {"description", "read", "write"}:
            raise ValueError(f"API Primitive {aid} must contain only description, read, and write at this stage")
        if not isinstance(api["description"], str) or not api["description"].strip():
            raise ValueError(f"API description is required: {aid}")
        validate_record({key: api[key] for key in ("read", "write")}, symbols, aid)
    for rid, ids in design["requirements"].items():
        if rid not in obligations["requirements"] or not isinstance(ids, list) or any(not isinstance(aid, str) for aid in ids):
            raise ValueError(f"Invalid requirement/API binding: {rid}")
        if len(ids) != len(set(ids)) or set(ids) - set(design["apis"]):
            raise ValueError(f"Duplicate or unknown API binding: {rid}")
        assigned = [design["apis"][aid] for aid in ids]
        combined = union(assigned)
        required = obligations["requirements"][rid]
        if tree is None:
            report = coverage(required, assigned)
        else:
            inherited = set(ids) & descendant_apis(tree, design, rid)
            if inherited:
                raise ValueError(f"Parent {rid} must not bind descendant APIs {sorted(inherited)}; regenerate steps 06 and 07")
            scope = requirement_scope(tree, obligations, rid)
            required = scope["required"]
            report = {
                "missing": difference(scope["required"], combined),
                "excess": difference(combined, scope["allowed"]),
                "subtree_missing": difference(obligations["requirements"][rid], union([scope["children"], combined])),
            }
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
