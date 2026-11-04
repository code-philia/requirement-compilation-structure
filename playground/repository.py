"""Discover local output workspaces and read immutable playground run archives."""

import hashlib
from pathlib import Path
import re
import time

from failures import collect_failures

from metrics import (
    aggregate,
    calls_from_records,
    log_records,
    read_json,
    seconds_between,
    recorded_stages,
    calls_from_terminal,
    telemetry_summary,
    metrics_from_totals,
    MODEL_PRICES,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = (
    "requirements",
    "visual_analysis",
    "db_schema",
    "db_obligations",
    "db_checks",
    "backend_apis",
    "backend_tdd",
    "ui_design",
    "ui_checks",
    "frontend_triggers",
    "frontend_e2e",
    "independent_acceptance",
    "compilation",
)
STAGES = [
    ("00_project_initialization", "项目初始化", "准备工作台"),
    ("01_explore_requirement", "读取需求", "需求档案站"),
    ("02_build_db_schema", "数据库设计", "数据仓库"),
    ("03_infer_db_obligations", "读写义务分析", "数据仓库"),
    ("04_implement_db", "实现数据库", "数据仓库"),
    ("05_design_backend_apis", "API 契约设计", "API 工坊"),
    ("06_implement_backend_tdd", "后端实现与验收", "API 工坊"),
    ("07_design_ui", "界面设计", "界面装配区"),
    ("08_implement_ui", "界面实现", "界面装配区"),
    ("09_design_frontend_triggers", "交互设计", "界面装配区"),
    ("10_implement_frontend_tdd", "逐需求实现与验收", "质量检查台"),
]


class Repository:
    def __init__(self):
        self.entries = {}
        self.extra_outputs = set()
        self.last_scan = 0
        self.cache = {}
        self.log_cache = {}
        self.prices = MODEL_PRICES

    def scan(self, force=False):
        if not force and time.monotonic() - self.last_scan < 10:
            return list(self.entries.values())
        outputs = set(self.extra_outputs)
        output_root = ROOT / "outputs"
        if output_root.is_dir():
            for output in output_root.iterdir():
                if output.is_symlink() or not output.is_dir():
                    continue
                if (output / ".arc").is_dir():
                    outputs.add(output)
        entries = {}
        for output in outputs:
            if not (output / ".arc").is_dir():
                continue
            run_root = output / ".arc" / "playground" / "runs"
            if run_root.is_dir():
                for run_dir in run_root.iterdir():
                    manifest = read_json(run_dir / "run.json")
                    if manifest:
                        identity = manifest["id"]
                        entries[identity] = {
                            "id": identity,
                            "output": output,
                            "archive": run_dir,
                            "manifest": manifest,
                        }
            # Existing files may contain several appended invocations. Keep that
            # provenance explicit instead of claiming they represent one exact run.
            if not run_root.exists():
                identity = (
                    "history-" + hashlib.sha256(str(output).encode()).hexdigest()[:16]
                )
                entries[identity] = {
                    "id": identity,
                    "output": output,
                    "archive": None,
                    "manifest": None,
                }
        self.entries = entries
        self.last_scan = time.monotonic()
        return list(entries.values())

    def get(self, identity):
        self.scan()
        entry = self.entries.get(identity)
        if entry is None:
            raise ValueError("运行记录不存在")
        return entry

    def summary(self, entry):
        output, archive = entry["output"], entry["archive"]
        manifest = read_json(archive / "run.json") if archive else {}
        report = read_json(output / ".arc" / "compilation.json") if not archive else {}
        if not manifest:
            modified = (output / ".arc").stat().st_mtime
            manifest = {
                "id": entry["id"],
                "name": output.name,
                "status": report.get("status", "HISTORICAL"),
                "started_at": None,
                "sort_time": modified,
                "settings": {},
                "legacy": True,
                "output": str(output.relative_to(ROOT)),
                "stages": report.get("stages", {}),
            }
        return manifest

    def detail(self, identity):
        entry = self.get(identity)
        run = self.summary(entry)
        output, archive = entry["output"], entry["archive"]
        base = archive / "artifacts" if archive else output / ".arc"
        logs = archive or output
        console_path = logs / ("console.log" if archive else "compiler.log")
        model_path = logs / "model_calls.jsonl"
        events_path = logs / "compilation_events.jsonl"
        signature = []
        for path in (console_path, model_path, events_path):
            try:
                signature.append((path.stat().st_size, path.stat().st_mtime_ns))
            except OSError:
                signature.append(None)
        cached = self.cache.get(identity)
        if cached is None or cached[0] != signature:
            records = list(log_records(events_path))
            telemetry = None
            if records:
                latest_run = records[-1].get("run_id")
                telemetry = telemetry_summary(
                    record for record in records if record.get("run_id") == latest_run
                )
                calls = telemetry["calls"]
                recorded = {}
            else:
                calls = calls_from_records(log_records(model_path))
                if not calls:
                    calls = calls_from_terminal(console_path)
                recorded = recorded_stages(console_path)
            cached = (signature, calls, telemetry, recorded)
            self.cache[identity] = cached
        _, cached_calls, telemetry, recorded = cached
        calls = [dict(call) for call in cached_calls]
        artifacts = {name: read_json(base / (name + ".json")) for name in ARTIFACTS}
        metrics = aggregate(calls, self.prices)
        settings = dict(run.get("settings", {}))
        settings.update(prices=self.prices, currency="CNY", pricing_period="peak")
        if not settings.get("model"):
            settings["model"] = next(
                (call["model"] for call in calls if call.get("model")), None
            )
        if not settings.get("base_url"):
            settings["base_url"] = next(
                (call.get("base_url") for call in calls if call.get("base_url")), None
            )
        run["settings"] = settings
        stage_definitions = STAGES
        stage_records = dict(run.get("stages", {}))
        tasks, actions = [], []
        if telemetry:
            run.update(telemetry["run"])
            run["legacy"] = False
            settings.update(telemetry["run"].get("settings", {}))
            stage_records = telemetry["stages"]
            tasks = [dict(task) for task in telemetry["tasks"]]
            actions = [dict(action) for action in telemetry["actions"]]
            parents = {task["id"]: task.get("parent_id") for task in tasks}
            for task in tasks:
                if "usage" in task:
                    task["metrics"] = metrics_from_totals(task["usage"])
                    continue
                task_calls = []
                for call in calls:
                    ancestor = call.get("task_span_id")
                    while ancestor:
                        if ancestor == task["id"]:
                            task_calls.append(call)
                            break
                        ancestor = parents.get(ancestor)
                task["metrics"] = aggregate(task_calls, self.prices)
            for action in actions:
                action["metrics"] = metrics_from_totals(action.get("usage", {}))
        elif run.get("legacy"):
            run["data_note"] = (
                "按历史日志中已报告的数据统计；未保存的模型输入输出和时间戳无法恢复。费用按高峰期人民币单价估算。"
            )
            if recorded:
                known = {stage[:2]: stage for stage in stage_records}
                stage_records = {}
                stage_definitions = []
                for code, record in recorded.items():
                    stage_key = known.get(code, record["id"])
                    stage_records[stage_key] = record
                    stage_definitions.append((stage_key, record["label"], "已记录阶段"))
            if (
                run.get("seconds") is None
                and recorded
                and all(
                    record.get("seconds") is not None for record in recorded.values()
                )
            ):
                run["seconds"] = sum(record["seconds"] for record in recorded.values())
                run["timing_source"] = "stage_timers"
                run["data_note"] += " 总耗时为已记录阶段耗时之和。"
        run["settings"] = settings
        requirement_ids = []
        pending = [artifacts.get("requirements", {})]
        while pending:
            node = pending.pop()
            if not isinstance(node, dict):
                continue
            if node.get("id"):
                requirement_ids.append(node["id"])
            pending.extend(node.get("children") or [])
        groups = {}
        for call in calls:
            if call.get("task_span_id"):
                continue
            owners = [
                rid
                for rid in requirement_ids
                if re.search(
                    r"(?<![\w.-])" + re.escape(rid) + r"(?![\w.-])", call["activity"]
                )
            ]
            task_id = call["activity"].split(" | ", 1)[0]
            if len(owners) == 1:
                task_id = owners[0]
            for api_id in artifacts.get("backend_apis", {}).get("apis", {}):
                if api_id in call["activity"]:
                    task_id = api_id
                    break
            group_id = f"recorded-task:{call['stage']}:{task_id}"
            call.update(task_id=task_id, task_span_id=group_id, requirement_ids=owners)
            group = groups.setdefault(
                group_id,
                {
                    "id": group_id,
                    "task_id": task_id,
                    "stage": call["stage"],
                    "requirement_ids": owners,
                    "seconds": None,
                    "parent_id": None,
                    "status": "RECORDED",
                    "calls": [],
                },
            )
            group["calls"].append(call)
        for group in groups.values():
            group["metrics"] = aggregate(group.pop("calls"), self.prices)
            tasks.append(group)
        stages = []
        for stage_key, label, zone in stage_definitions:
            record = stage_records.get(stage_key, {})
            stage_calls = [call for call in calls if call["stage"] == stage_key[:2]]
            stages.append(
                {
                    "id": stage_key,
                    "label": label,
                    "zone": zone,
                    "status": record.get(
                        "status", "RECORDED" if stage_calls else "PENDING"
                    ),
                    "seconds": record.get("seconds"),
                    "started_at": record.get("started_at"),
                    "error": record.get("error"),
                    "metrics": aggregate(stage_calls, self.prices),
                }
            )
        requirement_metrics = {}
        pending = [artifacts.get("requirements", {})]
        while pending:
            requirement = pending.pop()
            if not requirement.get("id"):
                continue
            children = requirement.get("children") or []
            pending.extend(children)
            descendants = set()
            subtree = [requirement]
            while subtree:
                node = subtree.pop()
                descendants.add(node["id"])
                subtree.extend(node.get("children") or [])
            assigned_calls, shared_calls = [], []
            for call in calls:
                owners = set(call.get("requirement_ids") or [])
                if owners and owners.issubset(descendants):
                    assigned_calls.append(call)
                elif owners.intersection(descendants):
                    shared_calls.append(call)
            assigned_tasks = [
                task
                for task in tasks
                if not task.get("parent_id")
                and task.get("requirement_ids")
                and set(task["requirement_ids"]).issubset(descendants)
            ]
            task_seconds = None
            if assigned_tasks and all(
                task.get("seconds") is not None for task in assigned_tasks
            ):
                task_seconds = sum(task["seconds"] for task in assigned_tasks)
            requirement_metrics[requirement["id"]] = {
                "metrics": aggregate(assigned_calls, self.prices),
                "seconds": task_seconds,
                "shared_calls": len(shared_calls),
            }
        duration = run.get("seconds")
        if duration is None and run.get("started_at"):
            from datetime import datetime, timezone

            duration = seconds_between(
                run["started_at"],
                run.get("finished_at") or datetime.now(timezone.utc).isoformat(),
            )
        return {
            "run": run,
            "metrics": metrics,
            "seconds": duration,
            "stages": stages,
            "calls": calls,
            "requirements": requirement_metrics,
            "tasks": tasks,
            "actions": actions,
            "artifacts": artifacts,
            "failures": collect_failures(artifacts, stages, calls),
        }

    def call_detail(self, identity, call_id):
        entry = self.get(identity)
        path = (
            entry["archive"] / "model_calls.jsonl"
            if entry["archive"]
            else entry["output"] / "model_calls.jsonl"
        )
        records = [
            record
            for record in log_records(path)
            if record.get("call_id") == call_id
            and record.get("event") in {"request", "response", "error"}
        ]
        if records:
            return records
        detail = self.detail(identity)
        call = next((call for call in detail["calls"] if call["id"] == call_id), None)
        if call is None:
            raise ValueError("模型调用不存在")
        return [
            {
                "event": "summary",
                "summary": call,
                "note": "此运行未保存完整模型输入输出；统计摘要来自结构化事件或终端日志。",
            }
        ]

    def log(self, identity, offset=0):
        entry = self.get(identity)
        path = (
            entry["archive"] / "console.log"
            if entry["archive"]
            else entry["output"] / "compiler.log"
        )
        try:
            with path.open("rb") as stream:
                size = path.stat().st_size
                start = max(0, size - 120_000) if offset == 0 else min(offset, size)
                stream.seek(start)
                content = stream.read(120_000)
                position = stream.tell()
            return {
                "text": re.sub(
                    r"\x1b\[[0-9;]*[a-zA-Z]",
                    "",
                    content.decode("utf-8", errors="replace"),
                ),
                "offset": position,
                "truncated": start > 0 and offset == 0,
            }
        except OSError:
            return {"text": "", "offset": 0, "truncated": False}
