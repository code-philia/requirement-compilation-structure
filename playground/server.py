"""Local-only React playground and compiler process supervisor.

Start: .venv/bin/python playground/server.py --port 0
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from uuid import uuid4
from contextlib import asynccontextmanager

import httpx
from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from metrics import read_json, write_json, MODEL_PRICES
from repository import ROOT, Repository, STAGES

HERE = Path(__file__).resolve().parent
repository = Repository()
repository.prices = MODEL_PRICES
processes = {}
run_lock = threading.Lock()
# Credentials live only in this server's memory, never in manifests or browser storage.
configuration = dict(dotenv_values(ROOT / ".env", encoding="utf-8-sig"))
configuration.update(
    {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "MODEL",
            "MODEL_REASONING",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "VISUAL_MODEL",
            "VISUAL_API_KEY",
            "VISUAL_BASE_URL",
        }
    }
)


class Settings(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    reasoning: str = "low"
    visual_model: str = ""
    visual_base_url: str = ""
    visual_api_key: str = ""


class StartRun(Settings):
    input: str
    output: str
    stage: str = ""
    port: int = Field(default=3000, ge=1, le=65535)


def local_path(value):
    if not value or Path(value).is_absolute():
        raise ValueError("请填写相对于 compiler 的目录")
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT) or path == ROOT:
        raise ValueError("目录必须位于 compiler 工作区内")
    return path


def public_settings():
    return {
        "base_url": configuration.get("OPENAI_BASE_URL") or "https://api.openai.com/v1",
        "model": configuration.get("MODEL") or "deepseek-flash",
        "key_set": bool(configuration.get("OPENAI_API_KEY")),
        "visual_model": configuration.get("VISUAL_MODEL") or "",
        "visual_base_url": configuration.get("VISUAL_BASE_URL") or "",
        "visual_key_set": bool(configuration.get("VISUAL_API_KEY")),
        "reasoning": configuration.get("MODEL_REASONING") or "low",
    }


def update_settings(settings):
    for name, key in (
        ("base_url", "OPENAI_BASE_URL"),
        ("model", "MODEL"),
        ("reasoning", "MODEL_REASONING"),
        ("visual_model", "VISUAL_MODEL"),
        ("visual_base_url", "VISUAL_BASE_URL"),
    ):
        value = getattr(settings, name)
        if name in {"visual_model", "visual_base_url"} or value:
            configuration[key] = value
    if settings.api_key:
        configuration["OPENAI_API_KEY"] = settings.api_key
    if settings.visual_api_key:
        configuration["VISUAL_API_KEY"] = settings.visual_api_key


def stop_process(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGINT)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


@asynccontextmanager
async def lifespan(app):
    # An archive left RUNNING after a service crash is interrupted, not successful.
    for entry in repository.scan(force=True):
        if entry["archive"]:
            manifest = repository.summary(entry)
            if manifest.get("status") == "RUNNING":
                manifest.update(
                    status="INTERRUPTED", error="本地服务已结束，上次运行未记录完整结果"
                )
                for stage in manifest.get("stages", {}).values():
                    if stage.get("status") == "RUNNING":
                        stage["status"] = "INTERRUPTED"
                write_json(entry["archive"] / "run.json", manifest)
    yield
    for process in list(processes.values()):
        await asyncio.to_thread(stop_process, process)


app = FastAPI(title="Requirement Factory", lifespan=lifespan)


@app.exception_handler(ValueError)
async def value_error(request, error):
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": str(error)}, status_code=400)


@app.middleware("http")
async def local_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if (
        origin
        and origin != str(request.base_url).rstrip("/")
        and origin not in {"http://127.0.0.1:5173", "http://localhost:5173"}
    ):
        return JSONResponse({"detail": "不允许来自其他网站的请求"}, status_code=403)
    return await call_next(request)


@app.get("/api/config")
def config():
    return {
        "root": str(ROOT),
        "settings": public_settings(),
        "stages": [
            {"id": identity, "label": label, "zone": zone}
            for identity, label, zone in STAGES
        ],
        "active": [
            identity
            for identity, process in processes.items()
            if process.poll() is None
        ],
        "prices": repository.prices,
    }


@app.post("/api/settings")
def settings(body: Settings):
    update_settings(body)
    return public_settings()


@app.post("/api/models")
def models(body: Settings):
    update_settings(body)
    base = configuration.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    key = configuration.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("请先填写 API Key")
    try:
        response = httpx.get(
            base.rstrip("/") + "/models",
            headers={"Authorization": "Bearer " + key},
            timeout=15,
            trust_env=False,
        )
        response.raise_for_status()
        return {
            "models": sorted(
                item["id"]
                for item in response.json().get("data", [])
                if isinstance(item.get("id"), str)
            )
        }
    except (httpx.HTTPError, ValueError) as error:
        raise ValueError(
            "无法获取模型列表，可手动输入模型 ID。" + type(error).__name__
        ) from error


@app.get("/api/directories")
def directories(prefix: str = "", kind: str = "input"):
    if not prefix:
        parent, fragment = ROOT, ""
    else:
        path = local_path(prefix)
        parent = path if prefix.endswith("/") else path.parent
        fragment = "" if prefix.endswith("/") else path.name
    if not parent.is_dir():
        return {"items": []}
    items = []
    for path in sorted(parent.iterdir()):
        if (
            not path.is_dir()
            or path.name.startswith(".")
            or path.name == "node_modules"
            or not path.name.startswith(fragment)
        ):
            continue
        if not path.resolve().is_relative_to(ROOT):
            continue
        items.append(
            {
                "path": str(path.relative_to(ROOT)),
                "requirements": (path / "requirements.yaml").is_file(),
            }
        )
    return {"items": items[:40]}


@app.get("/api/validate")
def validate(input: str, output: str, stage: str = ""):
    source, target = local_path(input), local_path(output)
    if not (source / "requirements.yaml").is_file():
        raise ValueError("输入目录中没有 requirements.yaml")
    if (
        target.is_file()
        or source == target
        or target in source.parents
        or source in target.parents
    ):
        raise ValueError("输入与输出目录不可重叠，输出路径必须是目录")
    protected = {
        "infrastructure",
        "tests",
        "scripts",
        "playground",
        ".git",
        ".venv",
        ".codex",
        ".agents",
    }
    if target.relative_to(ROOT).parts[0] in protected:
        raise ValueError("输出目录不可覆盖编译器或 playground 源码")
    dependencies = {
        "01": [],
        "02": ["requirements"],
        "03": ["requirements", "db_schema"],
        "04": ["requirements", "db_schema"],
        "05": ["requirements", "db_schema", "db_obligations"],
        "06": ["requirements", "db_schema", "db_obligations", "backend_apis"],
        "07": ["requirements"],
        "08": ["requirements", "ui_design"],
        "09": [
            "requirements",
            "db_schema",
            "db_obligations",
            "backend_apis",
            "ui_design",
        ],
        "10": [
            "requirements",
            "db_schema",
            "db_obligations",
            "backend_apis",
            "ui_design",
            "frontend_triggers",
        ],
    }
    missing = [
        name + ".json"
        for name in dependencies.get(stage[:2], [])
        if not (target / ".arc" / (name + ".json")).is_file()
    ]
    return {
        "input": str(source),
        "output": str(target),
        "exists": target.exists(),
        "missing": missing,
    }


@app.get("/api/runs")
def runs(search: str = "", limit: int = 60, offset: int = 0):
    entries = [repository.summary(entry) for entry in repository.scan()]
    entries.sort(
        key=lambda entry: str(entry.get("started_at") or entry.get("sort_time") or ""),
        reverse=True,
    )
    if search:
        entries = [
            entry
            for entry in entries
            if search.lower() in json.dumps(entry, ensure_ascii=False).lower()
        ]
    return {
        "items": entries[max(0, offset) : max(0, offset) + min(limit, 100)],
        "total": len(entries),
    }


@app.get("/api/runs/{identity}")
def detail(identity: str):
    return repository.detail(identity)


@app.get("/api/runs/{identity}/reference")
def reference(identity: str, path: str):
    entry = repository.get(identity)
    run = repository.summary(entry)
    if not run.get("input"):
        raise ValueError("此历史记录没有保存输入目录")
    source = local_path(run["input"])
    image = (source / path).resolve()
    if (
        not image.is_relative_to(source)
        or not image.is_file()
        or image.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    ):
        raise ValueError("参考图片不存在或格式不受支持")
    return FileResponse(image)


@app.get("/api/runs/{identity}/calls/{call_id}")
def call_detail(identity: str, call_id: str):
    return repository.call_detail(identity, call_id)


@app.get("/api/runs/{identity}/log")
def log(identity: str, offset: int = 0):
    return repository.log(identity, max(offset, 0))


@app.get("/api/runs/{identity}/events")
async def events(identity: str, request: Request):
    entry = repository.get(identity)
    base = entry["archive"] or entry["output"]

    async def stream():
        previous = None
        while not await request.is_disconnected():
            paths = [
                base / "run.json",
                base / "events.jsonl",
                base / "model_calls.jsonl",
                base / "compilation_events.jsonl",
            ]
            if not entry["archive"]:
                paths.append(entry["output"] / "compiler.log")
                paths.extend(
                    entry["output"] / ".arc" / (name + ".json")
                    for name in (
                        "compilation",
                        "db_schema",
                        "ui_design",
                        "backend_apis",
                        "frontend_triggers",
                        "backend_tdd",
                        "db_checks",
                        "ui_checks",
                        "frontend_e2e",
                        "independent_acceptance",
                    )
                )
            signature = []
            for path in paths:
                try:
                    signature.append((path.stat().st_mtime_ns, path.stat().st_size))
                except OSError:
                    signature.append(None)
            if signature != previous:
                previous = signature
                yield "event: update\ndata: {}\n\n"
            else:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1.2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/runs")
def start(body: StartRun):
    valid = validate(body.input, body.output, body.stage)
    if body.stage and body.stage not in {identity for identity, _, _ in STAGES}:
        raise ValueError("未知编译阶段")
    if valid["missing"]:
        raise ValueError("缺少前置产物：" + ", ".join(valid["missing"]))
    if body.reasoning not in {"auto", "provider", "none", "low", "high", "max"}:
        raise ValueError("未知 reasoning 设置")
    with run_lock:
        if any(process.poll() is None for process in processes.values()):
            raise ValueError("已有编译任务正在运行，请等待完成或先停止")
        update_settings(body)
        if not configuration.get("OPENAI_API_KEY"):
            raise ValueError("请填写 API Key")
        identity = (
            datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:6]
        )
        output = Path(valid["output"])
        archive = output / ".arc" / "playground" / "runs" / identity
        manifest = {
            "id": identity,
            "name": output.name,
            "input": body.input,
            "output": body.output,
            "status": "RUNNING",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "stages": {},
            "settings": {
                "model": configuration.get("MODEL"),
                "base_url": configuration.get("OPENAI_BASE_URL"),
                "reasoning": body.reasoning,
                "visual_model": body.visual_model or configuration.get("MODEL"),
                "visual_base_url": body.visual_base_url
                or configuration.get("OPENAI_BASE_URL"),
                "stage": body.stage,
                "port": body.port,
                "prices": repository.prices,
                "currency": "CNY",
                "pricing_period": "peak",
            },
        }
        write_json(archive / "run.json", manifest)
        environment = {
            key: configuration.get(key)
            for key in ("MODEL", "OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL_REASONING")
        }
        visual_override = bool(
            body.visual_model or body.visual_base_url or body.visual_api_key
        )
        environment.update(
            VISUAL_MODEL=body.visual_model or configuration.get("MODEL"),
            VISUAL_API_KEY=(
                configuration.get("VISUAL_API_KEY")
                or configuration.get("OPENAI_API_KEY")
            )
            if visual_override
            else configuration.get("OPENAI_API_KEY"),
            VISUAL_BASE_URL=body.visual_base_url
            or configuration.get("OPENAI_BASE_URL"),
        )
        source_log = output / "model_calls.jsonl"
        event_log = output / "compilation_events.jsonl"
        config = {
            "run_dir": str(archive),
            "output": str(output),
            "input": valid["input"],
            "environment": environment,
            "stage": body.stage,
            "port": body.port,
            "model_offset": source_log.stat().st_size if source_log.exists() else 0,
            "event_offset": event_log.stat().st_size if event_log.exists() else 0,
        }
        process = subprocess.Popen(
            [sys.executable, "-u", str(HERE / "worker.py")],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        processes[identity] = process
        process.stdin.write((json.dumps(config) + "\n").encode())
        process.stdin.close()
        secrets = [
            value for key, value in environment.items() if "KEY" in key and value
        ]

        def collect():
            with (archive / "console.log").open("w", encoding="utf-8") as log:
                for line in iter(process.stdout.readline, b""):
                    text = line.decode("utf-8", errors="replace")
                    for secret in secrets:
                        text = text.replace(secret, "[REDACTED]")
                    log.write(text)
                    log.flush()
            process.wait()
            current = read_json(archive / "run.json")
            if current.get("status") == "RUNNING":
                current.update(
                    status="FAILED",
                    error="编译进程未正常完成",
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                for stage in current.get("stages", {}).values():
                    if stage.get("status") == "RUNNING":
                        stage["status"] = "FAILED"
                write_json(archive / "run.json", current)

        threading.Thread(target=collect, daemon=True).start()
        repository.extra_outputs.add(output)
        repository.scan(force=True)
        return {"id": identity}


@app.post("/api/runs/{identity}/stop")
def stop(identity: str):
    process = processes.get(identity)
    if not process or process.poll() is not None:
        raise ValueError("此运行当前没有活动进程")
    stop_process(process)
    return {"status": "INTERRUPTED"}


if (HERE / "dist").exists():
    app.mount("/assets", StaticFiles(directory=HERE / "dist" / "assets"), name="assets")


@app.get("/{path:path}")
def index(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "接口不存在")
    file = HERE / "dist" / "index.html"
    if not file.is_file():
        raise HTTPException(503, "请先在 playground 中运行 npm run build")
    return FileResponse(file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", args.port))
    listener.listen(128)
    print(
        f"\n  Requirement Factory → http://127.0.0.1:{listener.getsockname()[1]}\n",
        flush=True,
    )
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[listener])
