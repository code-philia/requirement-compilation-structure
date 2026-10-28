"""Semantic event P/Q; implementation and E2E checks validate the described behavior."""

from infrastructure.stages.frontend.interactions.design import require_fields, text


def validate_contract(eid, contract):
    """Accept only simple P/Q string lists; a result must be described for every event."""
    require_fields(contract, {"precondition", "postcondition"}, f"Event contract {eid}")
    for kind, conditions in contract.items():
        if not isinstance(conditions, list) or (kind == "postcondition" and not conditions):
            raise ValueError(f"{eid}.{kind} must be a list; postcondition must not be empty")
        for condition in conditions:
            text(condition, f"{eid}.{kind}")
        if len(set(conditions)) != len(conditions):
            raise ValueError(f"Duplicate {kind} descriptions: {eid}")
