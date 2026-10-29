"""Event P/Q JSON containers without semantic condition gates."""

from infrastructure.shared.models.structure import object_fields, string_list


def validate_contract(eid, contract):
    object_fields(contract, {"precondition": list, "postcondition": list}, f"event {eid} contract")
    for kind in ("precondition", "postcondition"):
        string_list(contract[kind], f"{eid}.{kind}")
