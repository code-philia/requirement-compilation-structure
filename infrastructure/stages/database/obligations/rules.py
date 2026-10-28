"""Bottom-up, upward-only propagation; downward allocation remains a TODO."""

from copy import deepcopy

from infrastructure.stages.requirements.tree import RequirementTree


def union(records) -> dict:
    """Combine read and write sets independently and return deterministic sorted lists."""
    records = list(records)
    return {mode: sorted({field for record in records for field in record[mode]}) for mode in ("read", "write")}


def difference(left: dict, right: dict) -> dict:
    """Return read/write fields present on the left but absent on the right; use this to report coverage gaps."""
    return {mode: sorted(set(left[mode]) - set(right[mode])) for mode in ("read", "write")}


def propagate_obligations(tree: RequirementTree, obligations: dict, on_node=None) -> dict:
    """Preserve every original obligation and step; add lower-level fields upward."""
    result = {kind: deepcopy(obligations[kind]) for kind in ("requirements", "steps")}
    result["todos"] = []
    # --- Rule 1: visit descendants before their parent ------------------------
    # Changing the traversal may require a fixed-point iteration; postorder
    # gives the current upward-only policy its closure in one traversal.
    for rid in tree.postorder:
        before = deepcopy(result["requirements"][rid])
        steps = {sid: result["steps"][sid] for sid in tree.own_steps[rid]}
        children = {cid: result["requirements"][cid] for cid in tree.children[rid]}
        # --- Key extension point: upward completion policy --------------------
        # O_X(node) <- O_X(node) union O_X(steps) union O_X(children).
        # Try provenance-aware propagation or another explicitly defined rule.
        # Preserve original obligations and keep read/write modes independent.
        after = union([before, *steps.values(), *children.values()])
        result["requirements"][rid] = after
        todos = []
        # --- Key extension point: coverage and future downward allocation -----
        # Coverage compares the upper set with the UNION of lower sets.
        # TODO: Allocate upper-level-only obligations to the correct child/step,
        # add missing scenarios, or correct an over-inferred upper obligation.
        # Never assign every field to every step: a rejection may have no writes.
        # Deciding the recipient requires semantic evidence: a missing behavior,
        # an omitted field binding, or an excessive upper inference are distinct.
        groups = []
        if children:
            groups.append(("children", children))
        if steps or not children:
            groups.append(("steps", steps))
        for coverage, group in groups:
            missing = difference(after, union(group.values()))
            if missing["read"] or missing["write"]:
                todos.append({"requirement": rid, "coverage": coverage, **missing})
        result["todos"].extend(todos)
        if on_node is not None:
            on_node(rid, before, after, {"steps": steps, "children": children}, todos)
    return result
