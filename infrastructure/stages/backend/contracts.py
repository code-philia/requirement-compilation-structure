"""API/condition JSON structure and preservation of DB obligation links."""

from infrastructure.shared.models.structure import object_fields, string_list
from infrastructure.stages.database.obligations.rules import union, difference

CONTRACT_KEYS = {"signature", "request", "response", "precondition", "postcondition"}
INTERFACE_KEYS = {"signature", "request", "response"}


def validate_interface(api):
    """Check container/value types, without route, JSON Schema or status policy checks."""
    object_fields(api, {"signature": dict, "request": dict, "response": dict}, "API interface")
    object_fields(api["signature"], {"name": str, "method": str, "path": str}, "signature")
    object_fields(api["response"], {"success": dict, "errors": list}, "response")
    for branch in [api["response"]["success"], *api["response"]["errors"]]:
        object_fields(branch, {"status": int, "body": (dict, bool), "headers": (dict, bool)}, "response branch")


def validate_contract(api):
    """Conditions are JSON records, not semantic proof obligations."""
    validate_interface(api)
    object_fields(api, {"precondition": list, "postcondition": list}, "API contract")
    for kind, status in (("precondition", "error_status"), ("postcondition", "status")):
        for condition in api[kind]:
            object_fields(condition, {"id": str, "description": str, status: int}, kind)


def validate_registry(apis, *, conditions=True):
    object_fields(apis, {}, "APIs")
    for api in apis.values():
        (validate_contract if conditions else validate_interface)(api)


def validate_contracts(value, design):
    """Keep API R/W and each requirement's aggregate DB effects linked to step 06."""
    object_fields(value, {"apis": dict, "requirements": dict}, "contracts")
    validate_registry(value["apis"])
    for aid, api in value["apis"].items():
        object_fields(api, {"read": list, "write": list}, aid)
        for mode in ("read", "write"):
            string_list(api[mode], f"{aid}.{mode}")
            if aid in design["apis"] and set(api[mode]) != set(design["apis"][aid][mode]):
                raise ValueError(f"API DB obligations changed: {aid}.{mode}")
    for rid, expected_ids in design["requirements"].items():
        ids = string_list(value["requirements"].get(rid, []), f"requirements.{rid}")
        unknown = set(ids) - set(value["apis"])
        if unknown:
            raise ValueError(f"Unknown APIs in obligation chain: {sorted(unknown)}")
        expected = union(design["apis"][aid] for aid in expected_ids)
        actual = union(value["apis"][aid] for aid in ids)
        if any(difference(expected, actual).values()) or any(difference(actual, expected).values()):
            raise ValueError(f"Contract DB obligations do not match API decomposition: {rid}")
