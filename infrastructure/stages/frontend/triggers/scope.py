"""Small model contexts without reducing the compiler's implementation or test scope.

Requirement implementation and repair see every required handler together.
Source dependencies and files named by failed checks are added as needed; tests
remain read-only except for the current suite during test generation.
"""

import json

from infrastructure.stages.frontend.triggers.design import api_ids

class TriggerCheckFailure(ValueError):
    """Keep full reports for logs while exposing structured, compact repair feedback."""

    def __init__(self, message, report):
        """Attach check results so the model need not parse a duplicated report string."""
        self.feedback = {"error": message, "checks": report}
        super().__init__(f"{message}: {report}")


def model_context(context, trigger_ids=None):
    """Supply selected triggers, complete page data, API contracts and derived DB effects."""
    selected = set(context["triggers"]) if trigger_ids is None else set(trigger_ids)
    triggers = {tid: context["triggers"][tid] for tid in sorted(selected)}
    called = {aid for trigger in triggers.values() for aid in api_ids(trigger)}
    result = {"page_subtrees": context["page_subtrees"], "triggers": triggers,
        "obligations": {tid: context["obligations"][tid] for tid in sorted(selected)},
        "target_trigger_ids": sorted(selected),
        "backend_apis": {aid: context["backend_apis"][aid] for aid in sorted(called)}}
    if "requirement" in context:
        result["requirement"] = context["requirement"]
    return result
