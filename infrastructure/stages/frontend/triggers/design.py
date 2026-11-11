"""Frontend triggers and database effects derived from their API actions."""

from copy import deepcopy

from infrastructure.stages.frontend.ui.design import page_context, page_elements
from infrastructure.stages.database.obligation_utils import union


def empty_triggers(tree):
    return {"triggers": {}, "requirements": {rid: [] for rid in tree.requirements},
        "steps": {sid: [] for sid in tree.steps}}


def relevant_pages(ui, rid):
    selected = set(ui["requirements"].get(rid, []))
    return {pid: page_context(ui, pid) for pid in ui["pages"] if selected.intersection(page_elements(ui, pid))}


def api_ids(trigger):
    return {action["api"] for action in trigger["action"] if action["kind"] == "api"}


def trigger_obligations(trigger, backend):
    """Compute DB R/W for implementation context, without frontend coverage gates."""
    return union(backend["apis"][aid] for aid in api_ids(trigger))


def apply_decomposition(current, proposal, rid):
    updated = deepcopy(current)
    updated["triggers"].update(deepcopy(proposal["triggers"]))
    updated["requirements"][rid] = proposal["requirement_triggers"]
    updated["steps"].update(deepcopy(proposal.get("step_triggers", {})))
    return updated


def validate_coverage(design, backend, obligations, tree, requirement_ids):
    """Compare declared calls with required DB effects, not source-code behavior.

    Step associations must be explicit. A step's calls may include conditional API
    branches with broader possible effects (e.g. a rejected registration), so only
    missing step effects are errors. Requirement reads are minimum capabilities;
    requirement writes retain exact coverage of their possible effects.
    """
    from infrastructure.stages.backend.primitives import ObligationCoverageError, coverage
    from infrastructure.stages.database.obligation_utils import difference
    for rid in requirement_ids:
        effects = [trigger_obligations(design['triggers'][tid], backend)
            for tid in design['requirements'][rid]]
        required = obligations['requirements'][rid]
        gaps = coverage(required, effects)
        if any(values for gap in gaps.values() for values in gap.values()):
            raise ObligationCoverageError(rid, required, union(effects), gaps)
        for sid in tree.own_steps[rid]:
            effects = [trigger_obligations(design['triggers'][tid], backend)
                for tid in design['steps'][sid]]
            required = obligations['steps'][sid]
            missing = difference(required, union(effects))
            if any(missing.values()):
                raise ObligationCoverageError(sid, required, union(effects), {'missing': missing})
