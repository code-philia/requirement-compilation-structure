"""Read SQL proposal JSON; executable behavior is checked by application tests."""

from infrastructure.shared.models.structure import object_fields


def validate_response(response, expected_path):
    """The compiler owns the destination; only SQL content is required from the response."""
    object_fields(response, {"content": str}, "SQL proposal")
    return response["content"]
