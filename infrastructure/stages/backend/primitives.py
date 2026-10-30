"""Requirement-to-API database obligation coverage."""

from copy import deepcopy
from infrastructure.stages.database.obligations.rules import difference, union


class ObligationCoverageError(ValueError):
    def __init__(self, rid, required, combined, gaps):
        self.feedback = {"requirement_id": rid, "required_obligations": required,
            "api_obligation_union": combined, **gaps}
        super().__init__(f"Obligation Propagation failed for {rid}: {self.feedback}")


def coverage(required, apis):
    combined = union(apis)
    return {"missing": difference(required, combined), "excess": difference(combined, required)}


def validate_design(design, obligations, complete=True, tree=None):
    """Compare read and write sets independently; no interface or schema policy."""
    expected = obligations["requirements"] if complete else design["requirements"]
    for rid in expected:
        if tree is not None and tree.children.get(rid):
            continue
        apis = [design["apis"][aid] for aid in design["requirements"].get(rid, [])]
        required = obligations["requirements"][rid]
        gaps = coverage(required, apis)
        if any(fields for gap in gaps.values() for fields in gap.values()):
            raise ObligationCoverageError(rid, required, union(apis), gaps)


def apply_decomposition(design, response, rid, obligations, tree=None):
    result = deepcopy(design)
    result["apis"].update(deepcopy(response["apis"]))
    result["requirements"][rid] = response["requirement_apis"]
    validate_design(result, obligations, complete=False, tree=tree)
    return result
