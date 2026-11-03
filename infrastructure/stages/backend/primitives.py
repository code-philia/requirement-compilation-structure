"""Requirement and scenario coverage over declared API database effects."""

from copy import deepcopy
from infrastructure.stages.database.obligations.rules import difference, union


class ObligationCoverageError(ValueError):
    def __init__(self, rid, required, combined, gaps):
        self.feedback = {"requirement_id": rid, "required_obligations": required,
            "api_obligation_union": combined, **gaps}
        super().__init__(f"Obligation Propagation failed for {rid}: {self.feedback}")


def coverage(required, apis):
    combined = union(apis)
    # Required reads are minimum capabilities, not a prohibition on supporting
    # lookups, joins or reusable response projections. Writes retain their boundary.
    return {"missing": difference(required, combined),
        "excess": {"read": [], "write": sorted(set(combined["write"]) - set(required["write"]))}}


def validate_design(design, obligations, complete=True, tree=None):
    """Check required reads, exact possible writes, and each scenario's API coverage."""
    expected = obligations["requirements"] if complete else design["requirements"]
    for rid in expected:
        if tree is not None and tree.children.get(rid):
            continue
        apis = [design["apis"][aid] for aid in design["requirements"][rid]]
        required = obligations["requirements"][rid]
        gaps = coverage(required, apis)
        if any(fields for gap in gaps.values() for fields in gap.values()):
            raise ObligationCoverageError(rid, required, union(apis), gaps)
        if tree is None:
            continue
        combined = union(apis)
        for sid in tree.own_steps[rid]:
            step_required = obligations["steps"][sid]
            missing = difference(step_required, combined)
            if any(missing.values()):
                raise ObligationCoverageError(sid, step_required, combined, {"missing": missing})


def apply_decomposition(design, response, rid, obligations, tree=None):
    result = deepcopy(design)
    result["apis"].update(deepcopy(response["apis"]))
    result["requirements"][rid] = response["requirement_apis"]
    validate_design(result, obligations, complete=False, tree=tree)
    return result
