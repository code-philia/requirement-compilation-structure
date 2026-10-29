"""API Primitive validation and requirement-to-API obligation conservation."""

from copy import deepcopy

from infrastructure.stages.database.obligations.records import validate_record
from infrastructure.stages.database.obligations.rules import difference, union
from infrastructure.stages.backend.contracts import validate_registry
from infrastructure.shared.models.structure import object_fields, string_list

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


def validate_design(design, obligations, symbols, complete=True, tree=None):
    """Check API JSON shape and requirement-to-API read/write coverage only."""
    object_fields(design, {"apis": dict, "requirements": dict}, "API design")
    for aid, api in design["apis"].items():
        object_fields(api, {"description": str, "read": list, "write": list,
            "signature": dict, "request": dict, "response": dict}, aid)
        validate_record(api, symbols, aid)
    validate_registry(design["apis"], conditions=False)
    for rid, ids in design["requirements"].items():
        string_list(ids, f"requirements.{rid}")
        if rid not in obligations["requirements"]:
            raise ValueError(f"Unknown requirement in obligation chain: {rid}")
        unknown = set(ids) - set(design["apis"])
        if unknown:
            raise ValueError(f"Unknown APIs in obligation chain: {sorted(unknown)}")
    expected = obligations["requirements"] if complete else design["requirements"]
    for rid in expected:
        if tree is not None and tree.children.get(rid):
            continue
        assigned = [design["apis"][aid] for aid in design["requirements"].get(rid, [])]
        required = obligations["requirements"][rid]
        report = coverage(required, assigned)
        if any(fields for gap in report.values() for fields in gap.values()):
            raise ObligationCoverageError(rid, required, union(assigned), report)


def apply_decomposition(design: dict, response: dict, rid: str, retrieved: dict, obligations: dict, symbols: set[str], tree=None) -> dict:
    """Apply one requirement's retrieved-API reuse and new API proposal to a copy, then validate before returning it."""
    object_fields(response, {"apis": dict, "requirement_apis": list}, "API proposal")
    result = deepcopy(design)
    result["apis"].update(deepcopy(response["apis"]))
    result["requirements"][rid] = string_list(response["requirement_apis"], "requirement_apis")
    validate_design(result, obligations, symbols, complete=False, tree=tree)
    return result
