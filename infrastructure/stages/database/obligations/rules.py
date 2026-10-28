"""Read/write set operations shared by API and interaction decomposition checks."""


def union(records) -> dict:
    """Combine read and write sets independently and return deterministic sorted lists."""
    records = list(records)
    return {mode: sorted({field for record in records for field in record[mode]}) for mode in ("read", "write")}


def difference(left: dict, right: dict) -> dict:
    """Return read/write fields present on the left but absent on the right; use this to report coverage gaps."""
    return {mode: sorted(set(left[mode]) - set(right[mode])) for mode in ("read", "write")}
