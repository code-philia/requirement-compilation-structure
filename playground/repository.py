"""Discover local output workspaces and read immutable playground run archives."""

import hashlib
import os
from pathlib import Path
import re
import time

from metrics import (
    aggregate,
    calls_from_records,
    log_records,
    read_json,
    seconds_between,
    recorded_stages,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = (
    "requirements",
    "visual_analysis",
    "db_schema",
    "db_obligations",
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
    ("10_implement_frontend_tdd", "交互实现与独立验收", "质量检查台"),
]


class Repository:
    def __init__(self):
        self.entries = {}
        self.extra_outputs = set()
        self.last_scan = 0
        self.cache = {}
        self.log_cache = {}
        self.prices = {}

    def scan(self, force=False):
        if not force and time.monotonic() - self.last_scan < 10:
            return list(self.entries.values())
        outputs = set(self.extra_outputs)
        for directory, subdirs, _ in os.walk(ROOT / "outputs"):
            subdirs[:] = [
                name
                for name in subdirs
                if name
                not in {
                    "node_modules",
                    ".git",
                    "dist",
                    "build",
                    "test-results",
                    "playwright-report",
                }
            ]
            if ".arc" in subdirs:
                outputs.add(Path(directory))
                subdirs[:] = []
        entries = {}
        for output in outputs:
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
            if (
                output / ".arc" / "requirements.json"
            ).exists() and not run_root.exists():
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
            modified = (output / ".arc" / "requirements.json").stat().st_mtime
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
        log_path = (
            archive / "model_calls.jsonl" if archive else output / "model_calls.jsonl"
        )
        try:
            signature = (log_path.stat().st_size, log_path.stat().st_mtime_ns)
        except OSError:
            signature = None
        cached = self.cache.get(identity)
        if not cached or cached[0] != signature:
            calls = calls_from_records(log_records(log_path))
            self.cache[identity] = (signature, calls)
        else:
            calls = cached[1]
        prices = run.get("settings", {}).get("prices", {}) if archive else self.prices
        metrics = aggregate(calls, prices)
        artifacts = {name: read_json(base / (name + ".json")) for name in ARTIFACTS}
        if run.get("legacy"):
            run["settings"] = {
                "model": next((call["model"] for call in calls if call["model"]), None),
                "base_url": next(
                    (call.get("base_url") for call in calls if call.get("base_url")),
                    None,
                ),
            }
            run["data_note"] = (
                "历史工作目录：日志可能包含多次执行；时间、设置及产物只展示可确认的数据。"
            )
        stages = []
        stage_definitions = STAGES
        if run.get("legacy"):
            console_path = output / "compiler.log"
            try:
                console_signature = (
                    console_path.stat().st_size,
                    console_path.stat().st_mtime_ns,
                )
            except OSError:
                console_signature = None
            previous = self.log_cache.get(run["id"])
            if previous is None or previous[0] != console_signature:
                recorded = recorded_stages(console_path)
                self.log_cache[run["id"]] = (console_signature, recorded)
            else:
                recorded = previous[1]
            if recorded:
                run["stages"] = {entry["id"]: entry for entry in recorded.values()}
                stage_definitions = [
                    (entry["id"], entry["label"], "历史执行阶段")
                    for entry in recorded.values()
                ]
            run["settings"]["prices"] = prices
            if prices:
                run["data_note"] += " 金额按当前配置单价估算。"
        for identity, label, zone in stage_definitions:
            entry = run.get("stages", {}).get(identity, {})
            stage_calls = [call for call in calls if call["stage"] == identity[:2]]
            stages.append(
                {
                    "id": identity,
                    "label": label,
                    "zone": zone,
                    "status": entry.get(
                        "status", "RECORDED" if stage_calls else "PENDING"
                    ),
                    "seconds": entry.get("seconds"),
                    "started_at": entry.get("started_at"),
                    "error": entry.get("error"),
                    "metrics": aggregate(stage_calls, prices),
                }
            )
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
            "artifacts": artifacts,
        }

    def call_detail(self, identity, call_id):
        entry = self.get(identity)
        path = (
            entry["archive"] / "model_calls.jsonl"
            if entry["archive"]
            else entry["output"] / "model_calls.jsonl"
        )
        return [
            record
            for record in log_records(path)
            if record.get("call_id") == call_id
            and record.get("event") in {"request", "response", "error"}
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
