"""Append-only compiler telemetry, independent of full prompt/response logging."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

import yaml
from dotenv import dotenv_values
from threading import RLock
from time import monotonic
from uuid import uuid4

from infrastructure.shared.models.pricing import (
    MODEL_PRICES,
    PRICE_TABLE,
    estimate_cost,
    normalize_usage,
)

_run = ContextVar("compiler_telemetry", default=None)
_task = ContextVar("compiler_telemetry_task", default=None)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def totals():
    return {
        "calls": 0,
        "usage_calls": 0,
        "priced_calls": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "model_seconds": 0,
        "cost_cny": 0,
        "currency": "CNY",
    }


def usage_snapshot(stats):
    result = dict(stats)
    result["cost_complete"] = stats["calls"] == stats["priced_calls"]
    if stats["calls"] and not stats["priced_calls"]:
        result["cost_cny"] = None
    return result


def emit(event, **fields):
    run = _run.get()
    if run is None:
        return
    task = _task.get()
    record = {
        "event": event,
        "timestamp": timestamp(),
        "run_id": run["id"],
        "stage": run.get("stage"),
        "task_id": task["task_id"] if task else None,
        "task_span_id": task["id"] if task else None,
        "requirement_ids": task["requirement_ids"] if task else [],
        **fields,
    }
    # Telemetry must not replace the compilation's original exception on I/O failure.
    try:
        with run["lock"]:
            with (run["output"] / "compilation_events.jsonl").open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as error:
        run["logging_error"] = str(error)


def begin_run(output, input_dir, stage):
    requirements = []
    try:
        pending = [
            yaml.safe_load(
                (input_dir / "requirements.yaml").read_text(encoding="utf-8-sig")
            )
        ]
        while pending:
            node = pending.pop()
            if not isinstance(node, dict):
                continue
            if isinstance(node.get("id"), str):
                requirements.append(node["id"])
            children = node.get("children")
            if isinstance(children, list):
                pending.extend(children)
    except (OSError, ValueError, yaml.YAMLError):
        pass
    output.mkdir(parents=True, exist_ok=True)
    state = {
        "id": os.getenv("COMPILER_RUN_ID") or uuid4().hex,
        "output": output,
        "started_at": timestamp(),
        "started": monotonic(),
        "stage": None,
        "lock": RLock(),
        "requirements": requirements,
        "prices": MODEL_PRICES,
        "totals": totals(),
        "stage_totals": totals(),
        "tasks": [],
        "action": None,
    }
    token = _run.set(state)
    defaults = dotenv_values(
        Path(__file__).resolve().parents[3] / ".env", encoding="utf-8-sig"
    )
    model = os.getenv("MODEL") or defaults.get("MODEL") or "deepseek-flash"
    base_url = (
        os.getenv("OPENAI_BASE_URL")
        or defaults.get("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    )
    emit(
        "run_started",
        input=str(input_dir),
        output=str(output),
        selected_stage=stage,
        pid=os.getpid(),
        settings={
            "model": model,
            "base_url": base_url,
            "stage": stage,
            "currency": "CNY",
        },
        pricing=PRICE_TABLE,
    )
    return token, state["id"]


def finish_run(token, status):
    run = _run.get()
    finish_action()
    result = {
        "run_id": run["id"],
        "started_at": run["started_at"],
        "finished_at": timestamp(),
        "seconds": monotonic() - run["started"],
        "usage": usage_snapshot(run["totals"]),
    }
    emit("run_finished", status=status, **result)
    _run.reset(token)
    return result


def begin_stage(stage):
    run = _run.get()
    if run is None:
        return None
    finish_action()
    run.update(
        stage=stage,
        stage_started=monotonic(),
        stage_started_at=timestamp(),
        stage_totals=totals(),
    )
    emit("stage_started")
    return stage


def finish_stage(stage, status):
    run = _run.get()
    if run is None or stage is None:
        return {}
    finish_action()
    result = {
        "started_at": run["stage_started_at"],
        "finished_at": timestamp(),
        "seconds": monotonic() - run["stage_started"],
        "usage": usage_snapshot(run["stage_totals"]),
    }
    emit("stage_finished", status=status, **result)
    run["stage"] = None
    return result


def task_metadata(label, requirement_ids=None):
    """Resolve only known IDs; shared tasks keep all owners without splitting their cost."""
    run = _run.get()
    metadata = {
        "task_id": label,
        "task_kind": "task",
        "requirement_ids": list(requirement_ids or []),
    }
    if run is None:
        return metadata
    if requirement_ids is None:
        for identity in run["requirements"]:
            if re.search(r"(?<![\w.-])" + re.escape(identity) + r"(?![\w.-])", label):
                metadata["requirement_ids"].append(identity)
    if label in run["requirements"]:
        metadata.update(task_id=label, task_kind="requirement")
        return metadata
    for filename, registry, kind in (
        ("backend_apis.json", "apis", "api"),
        ("ui_design.json", "pages", "page"),
    ):
        try:
            design = json.loads(
                (run["output"] / ".arc" / filename).read_text(encoding="utf-8-sig")
            )
        except (OSError, ValueError):
            continue
        for identity in design.get(registry, {}):
            if re.search(r"(?<![\w.-])" + re.escape(identity) + r"(?![\w.-])", label):
                metadata.update(task_id=identity, task_kind=kind)
                return metadata
    return metadata


@contextmanager
def task_scope(label, requirement_ids=None, result=None):
    run = _run.get()
    if run is None:
        yield
        return
    finish_action()
    parent = _task.get()
    task = {
        "id": uuid4().hex,
        "parent_id": parent["id"] if parent else None,
        "started": monotonic(),
        "started_at": timestamp(),
        "totals": totals(),
        **task_metadata(str(label), requirement_ids),
    }
    token = _task.set(task)
    run["tasks"].append(task)
    emit(
        "task_started",
        task_kind=task["task_kind"],
        parent_task_span_id=task["parent_id"],
    )
    status = "GREEN"
    try:
        yield
    except BaseException as error:
        status = "INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "FAILED"
        raise
    finally:
        finish_action()
        if status == "GREEN" and result is not None:
            status = result.get("status", status)
        emit(
            "task_finished",
            task_kind=task["task_kind"],
            parent_task_span_id=task["parent_id"],
            status=status,
            started_at=task["started_at"],
            seconds=monotonic() - task["started"],
            usage=usage_snapshot(task["totals"]),
        )
        run["tasks"].pop()
        _task.reset(token)


def begin_action(label):
    run = _run.get()
    if run is None:
        return
    finish_action()
    run["action"] = {
        "id": uuid4().hex,
        "label": label,
        "started": monotonic(),
        "started_at": timestamp(),
        "totals": totals(),
    }
    emit("action_started", action_id=run["action"]["id"], action=label)


def finish_action():
    run = _run.get()
    if run is None or run["action"] is None:
        return
    action = run["action"]
    emit(
        "action_finished",
        action_id=action["id"],
        action=action["label"],
        started_at=action["started_at"],
        seconds=monotonic() - action["started"],
        usage=usage_snapshot(action["totals"]),
    )
    run["action"] = None


def model_started(call_id, model, base_url):
    run = _run.get()
    if run is None:
        return
    action = run["action"]
    emit(
        "model_started",
        call_id=call_id,
        model=model,
        base_url=base_url,
        action_id=action["id"] if action else None,
        action=action["label"] if action else None,
    )


def model_finished(call_id, model, usage, seconds, status="GREEN", error=None):
    run = _run.get()
    if run is None:
        return
    normalized = normalize_usage(usage)
    amount = estimate_cost(model, normalized, run["prices"])
    targets = [run["totals"], run["stage_totals"]]
    targets.extend(task["totals"] for task in run["tasks"])
    if run["action"]:
        targets.append(run["action"]["totals"])
    for target in targets:
        target["calls"] += 1
        target["model_seconds"] += seconds
        if (
            normalized["input_tokens"] is not None
            and normalized["output_tokens"] is not None
        ):
            target["usage_calls"] += 1
        for name in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "total_tokens",
        ):
            target[name] += normalized[name] or 0
        if amount is not None:
            target["cost_cny"] += amount
            target["priced_calls"] += 1
    if error:
        for name in ("OPENAI_API_KEY", "VISUAL_API_KEY"):
            secret = os.getenv(name)
            if secret:
                error = error.replace(secret, "[REDACTED]")
    emit(
        "model_finished",
        call_id=call_id,
        model=model,
        status=status,
        seconds=seconds,
        usage=normalized,
        cost_cny=amount,
        currency="CNY",
        price=run["prices"].get(model),
        cached_usage_reported=normalized["cached_input_tokens"] is not None,
        error=error,
        action_id=run["action"]["id"] if run["action"] else None,
    )
