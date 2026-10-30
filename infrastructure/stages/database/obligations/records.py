"""Database field inventory and deterministic read/write normalization."""


def normalize_record(record):
    return {mode: sorted(set(record.get(mode, []))) for mode in ("read", "write")}


def normalize_inference(result, step_ids):
    return {"requirement": normalize_record(result["requirement"]),
        "steps": {sid: normalize_record(result.get("steps", {}).get(sid, {})) for sid in step_ids}}


def normalize_obligations(value, tree):
    return {kind: {key: normalize_record(value.get(kind, {}).get(key, {})) for key in expected}
        for kind, expected in (("requirements", tree.requirements), ("steps", tree.steps))}
