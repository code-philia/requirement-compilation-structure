"""Read call records and aggregate reported usage without counting HTTP envelopes twice."""

import json
from datetime import datetime
from pathlib import Path


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {} if default is None else default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def seconds_between(start, end):
    try:
        return max(
            0,
            (
                datetime.fromisoformat(end) - datetime.fromisoformat(start)
            ).total_seconds(),
        )
    except (TypeError, ValueError):
        return None


def stage_id(value):
    value = str(value or "")
    if value.startswith("Stage "):
        return value[6:8]
    return value[:2] if value[:2].isdigit() else "unknown"


def calls_from_records(records):
    calls = {}
    for record in records:
        identity = record.get("call_id")
        if not identity or record.get("event") not in {
            "request",
            "response",
            "error",
            "http_request",
        }:
            continue
        call = calls.setdefault(
            identity,
            {
                "id": identity,
                "stage": stage_id(record.get("stage")),
                "activity": record.get("activity", ""),
                "status": "RUNNING",
                "input": None,
                "output": None,
                "cached": None,
                "seconds": None,
                "model": None,
            },
        )
        if record["event"] == "request":
            arguments = record.get("arguments", {})
            call.update(
                started_at=record.get("timestamp"), model=arguments.get("model")
            )
        elif record["event"] == "response":
            response = record.get("response") or {}
            usage = response.get("usage") or {}
            details = (
                usage.get("prompt_tokens_details")
                or usage.get("input_tokens_details")
                or {}
            )
            call.update(
                status="GREEN",
                seconds=record.get("elapsed_seconds"),
                input=usage.get("prompt_tokens", usage.get("input_tokens")),
                output=usage.get("completion_tokens", usage.get("output_tokens")),
                cached=details.get(
                    "cached_tokens", usage.get("prompt_cache_hit_tokens")
                ),
                model=call["model"] or response.get("model"),
                response_model=response.get("model"),
                finished_at=record.get("timestamp"),
            )
        elif record["event"] == "http_request":
            url = record.get("url", "")
            call["base_url"] = url.rsplit("/chat/completions", 1)[0]
        else:
            call.update(
                status="FAILED",
                seconds=record.get("elapsed_seconds"),
                error=record.get("message"),
            )
    return list(calls.values())


def log_records(path, offset=0):
    try:
        with Path(path).open("rb") as source:
            source.seek(offset)
            for line in source:
                try:
                    yield json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
    except OSError:
        return


def aggregate(calls, prices):
    result = {
        "calls": len(calls),
        "input": 0,
        "output": 0,
        "cached": 0,
        "model_seconds": 0,
        "cost": 0 if not calls else None,
        "priced_calls": 0,
        "usage_calls": 0,
    }
    amount = 0
    for call in calls:
        result["model_seconds"] += call.get("seconds") or 0
        if call.get("input") is not None and call.get("output") is not None:
            result["usage_calls"] += 1
        for field in ("input", "output", "cached"):
            result[field] += call.get(field) or 0
        price = prices.get(call.get("model"))
        if not price or call.get("input") is None or call.get("output") is None:
            continue
        cached = call.get("cached") or 0
        amount += (
            (call["input"] - cached) * price["input"]
            + cached * price.get("cached", price["input"])
            + call["output"] * price["output"]
        ) / 1_000_000
        result["priced_calls"] += 1
    if result["priced_calls"]:
        result["cost"] = amount
    return result


def recorded_stages(path):
    """Use the actual stage names in terminal records, including repeated attempts."""
    import re

    stages = {}
    pending = None
    try:
        with Path(path).open(encoding="utf-8", errors="replace") as source:
            for line in source:
                match = re.search(
                    r"\[(START|DONE|FAILED)\] Stage (\d+) \|\s*(.+?)[│┃]*\s*$",
                    line.strip(),
                )
                if match:
                    outcome, code, label = match.groups()
                    entry = stages.setdefault(
                        code,
                        {
                            "id": code + "_recorded",
                            "label": label.strip(),
                            "status": "RECORDED",
                            "seconds": None,
                            "attempts": 0,
                        },
                    )
                    if outcome == "START":
                        entry["attempts"] += 1
                        entry["status"] = "RECORDED"
                    else:
                        entry["status"] = "GREEN" if outcome == "DONE" else "FAILED"
                        pending = code
                    continue
                timer = re.search(r"(?:Completed in|Stopped after) ([\d.]+)s", line)
                if pending and timer:
                    stages[pending]["seconds"] = (
                        stages[pending]["seconds"] or 0
                    ) + float(timer[1])
                    pending = None
    except OSError:
        pass
    return stages
