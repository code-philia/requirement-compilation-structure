"""Read call records and aggregate reported usage without counting HTTP envelopes twice."""

import json
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from infrastructure.shared.models.pricing import (
    MODEL_PRICES,
    PRICE_TABLE,
    estimate_cost,
)


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


def aggregate(calls, prices=None):
    result = {
        "currency": "CNY",
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
        usage = {
            "input_tokens": call.get("input"),
            "cached_input_tokens": call.get("cached"),
            "output_tokens": call.get("output"),
        }
        cost = estimate_cost(
            call.get("model"), usage, MODEL_PRICES if prices is None else prices
        )
        call["cost"] = cost
        call["currency"] = "CNY"
        if cost is not None:
            amount += cost
            result["priced_calls"] += 1
    if result["priced_calls"]:
        result["cost"] = amount
    return result


def recorded_stages(path):
    """Use the actual stage names in terminal records, including repeated attempts."""
    import re

    stages = {}
    pending = None
    pending_start = None
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
                        pending_start = code
                        entry["status"] = "RECORDED"
                    else:
                        entry["status"] = "GREEN" if outcome == "DONE" else "FAILED"
                        pending = code
                    continue
                if pending_start:
                    date = re.search(
                        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
                        line,
                    )
                    if date:
                        stages[pending_start]["started_at"] = date[0]
                        pending_start = None
                timer = re.search(r"(?:Completed in|Stopped after) ([\d.]+)s", line)
                if pending and timer:
                    stages[pending]["seconds"] = (
                        stages[pending]["seconds"] or 0
                    ) + float(timer[1])
                    pending = None
    except OSError:
        pass
    return stages


def calls_from_terminal(path):
    """Recover each untruncated usage summary once when full model I/O was disabled."""
    import re

    calls = []
    model = None
    current = None
    try:
        with Path(path).open(encoding="utf-8", errors="replace") as stream:
            for line_number, line in enumerate(stream, 1):
                match = re.search(r"\bModel: ([^\s│]+)", line)
                if match:
                    model = match[1]
                header = re.match(
                    r"--- \[MODEL OUTPUT\] Stage (\d+) \| [^|]+ \| (.+) \(full content\) ---",
                    line,
                )
                if header:
                    current = {
                        "id": f"terminal-{line_number}",
                        "stage": header[1],
                        "activity": header[2],
                        "model": model,
                        "status": "GREEN",
                        "input": None,
                        "cached": None,
                        "output": None,
                        "seconds": None,
                        "source": "terminal_summary",
                    }
                    calls.append(current)
                    continue
                if current is None:
                    continue
                if line.startswith("Reported tokens |"):
                    for label, key in (
                        ("input", "input"),
                        ("cached input", "cached"),
                        ("output", "output"),
                    ):
                        value = re.search(
                            r"\| " + label + r": ([\d,]+|unavailable)", line
                        )
                        if value and value[1] != "unavailable":
                            current[key] = int(value[1].replace(",", ""))
                latency = re.match(r"Round-trip latency: ([\d.]+) s", line)
                if latency:
                    current["seconds"] = float(latency[1])
                    current = None
    except OSError:
        pass
    return calls


def telemetry_summary(records):
    """Read one run's stage, task and action measurements from canonical events."""
    calls, stages, tasks, actions = {}, {}, {}, {}
    run = {}
    for record in records:
        event = record.get("event")
        stage = stage_id(record.get("stage"))
        if event == "run_started":
            run.update(
                started_at=record["timestamp"],
                run_id=record["run_id"],
                status="RUNNING",
                settings=record.get("settings", {}),
            )
            if record.get("pricing"):
                run["settings"]["prices"] = record["pricing"].get("models", {})
            if record.get("input"):
                source = Path(record["input"])
                root = Path(__file__).resolve().parents[1]
                run["input"] = (
                    str(source.relative_to(root))
                    if source.is_relative_to(root)
                    else str(source)
                )
        elif event == "run_finished":
            for key in ("status", "started_at", "finished_at", "seconds", "usage"):
                if key in record:
                    run[key] = record[key]
        elif event in {"stage_started", "stage_finished"}:
            entry = stages.setdefault(record["stage"], {})
            if event == "stage_started":
                entry.update(status="RUNNING", started_at=record["timestamp"])
            else:
                entry.update(
                    {
                        key: record.get(key)
                        for key in (
                            "status",
                            "started_at",
                            "finished_at",
                            "seconds",
                            "usage",
                        )
                    }
                )
        elif event in {"task_started", "task_finished"}:
            identity = record["task_span_id"]
            task = tasks.setdefault(
                identity,
                {
                    "id": identity,
                    "task_id": record.get("task_id"),
                    "requirement_ids": record.get("requirement_ids", []),
                    "stage": stage,
                    "parent_id": record.get("parent_task_span_id"),
                    "status": "RUNNING",
                    "started_at": record["timestamp"],
                },
            )
            if event == "task_finished":
                task.update(
                    status=record["status"],
                    seconds=record["seconds"],
                    usage=record["usage"],
                )
        elif event == "action_finished":
            actions[record["action_id"]] = {
                "id": record["action_id"],
                "task_span_id": record.get("task_span_id"),
                "action": record["action"],
                "stage": stage,
                "seconds": record["seconds"],
                "usage": record["usage"],
            }
        elif event in {"model_started", "model_finished"}:
            call = calls.setdefault(
                record["call_id"],
                {
                    "id": record["call_id"],
                    "stage": stage,
                    "activity": record.get("action")
                    or record.get("task_id")
                    or "模型调用",
                    "task_id": record.get("task_id"),
                    "task_span_id": record.get("task_span_id"),
                    "action_id": record.get("action_id"),
                    "requirement_ids": record.get("requirement_ids", []),
                    "source": "structured",
                    "status": "RUNNING",
                    "input": None,
                    "output": None,
                    "cached": None,
                    "seconds": None,
                },
            )
            if event == "model_started":
                call.update(
                    model=record.get("model"),
                    started_at=record["timestamp"],
                    base_url=record.get("base_url"),
                )
            else:
                usage = record["usage"]
                call.update(
                    model=record.get("model"),
                    status=record["status"],
                    seconds=record["seconds"],
                    input=usage["input_tokens"],
                    cached=usage["cached_input_tokens"],
                    output=usage["output_tokens"],
                    cost=record.get("cost_cny"),
                    currency="CNY",
                    error=record.get("error"),
                )
    return {
        "run": run,
        "calls": list(calls.values()),
        "stages": stages,
        "tasks": list(tasks.values()),
        "actions": list(actions.values()),
    }


def metrics_from_totals(usage):
    calls = usage.get("calls", 0)
    priced = usage.get("priced_calls", 0)
    cost = usage.get("cost_cny") if priced else (0 if calls == 0 else None)
    return {
        "calls": calls,
        "input": usage.get("input_tokens", 0),
        "cached": usage.get("cached_input_tokens", 0),
        "output": usage.get("output_tokens", 0),
        "usage_calls": usage.get("usage_calls", 0),
        "priced_calls": priced,
        "cost": cost,
        "currency": "CNY",
        "model_seconds": usage.get("model_seconds", 0),
    }
