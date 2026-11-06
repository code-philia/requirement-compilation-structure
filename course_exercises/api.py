"""Classroom API: independent credentials, one-call experiments and saved records."""

import asyncio
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from dotenv import dotenv_values
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .csv_reference import inspect_orders
from .model_client import estimate_cost, normalize_usage, response_text, stream_model

HERE = Path(__file__).resolve().parent
RECORDS = HERE / "records"
PRICING = json.loads((HERE / "pricing.json").read_text())
MODELS = {model["id"]: model for model in PRICING["models"]}
router = APIRouter(prefix="/api/course", tags=["classroom"])
profiles = {}
running = {}
records = {}
TASK_NAMES = {task["id"]: task["name"] for task in json.loads((HERE / "tasks.json").read_text(encoding="utf-8"))}


def initialize():
    RECORDS.mkdir(exist_ok=True)
    environment = dict(dotenv_values(HERE.parent / ".env", encoding="utf-8-sig"))
    environment.update(os.environ)
    for identity, model in MODELS.items():
        provider = model["provider"]
        prefix = "COURSE_QWEN" if provider == "qwen" else "COURSE_DEEPSEEK"
        common_url = environment.get("OPENAI_BASE_URL")
        base = (
            "https://dashscope.aliyuncs.com/compatible-mode/v1"
            if provider == "qwen"
            else "https://api.deepseek.com/v1"
        )
        key = (
            environment.get("DASHSCOPE_API_KEY")
            if provider == "qwen"
            else environment.get("OPENAI_API_KEY")
        )
        # A configured compatible gateway can serve all three classroom models.
        if provider == "qwen" and not key and common_url:
            key = environment.get("OPENAI_API_KEY")
        profiles[identity] = {
            "model": identity,
            "base_url": environment.get(prefix + "_BASE_URL")
            or (
                common_url
                if provider == "deepseek" or not environment.get("DASHSCOPE_API_KEY")
                else None
            )
            or base,
            "api_key": environment.get(prefix + "_API_KEY") or key or "",
        }
    for path in RECORDS.glob("*.json"):
        try:
            record = json.loads(path.read_text())
            if record["status"] == "RUNNING":
                record.update(
                    status="INTERRUPTED",
                    error="服务已重启，本次请求未正常完成",
                    finished_at=now(),
                )
                save(record)
            records[record["id"]] = record
        except (ValueError, OSError, KeyError):
            continue


def now():
    return datetime.now(timezone.utc).isoformat()


def save(record):
    path = RECORDS / (record["id"] + ".json")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def get_record(identity):
    record = records.get(identity)
    if record is None:
        raise HTTPException(404, "找不到这次课堂尝试")
    return record


def public_profile(identity):
    profile = profiles[identity]
    return {
        "model": profile["model"],
        "base_url": profile["base_url"],
        "key_set": bool(profile["api_key"]),
    }


def task_info(record):
    if record.get("task_id") == "custom-chat" or record.get("task_source") in {"custom", "prompt"}:
        return {"task_id": "custom-chat", "task_name": "自定义对话", "task_source": "custom", "task_kind": "custom"}
    if record.get("task_id"):
        return {
            "task_id": record["task_id"],
            "task_name": record.get("task_name") or TASK_NAMES.get(record["task_id"], "自由实验"),
            "task_source": record.get("task_source", "task"),
            "task_kind": "task",
        }
    prompt = record["prompt"]
    if all(field in prompt for field in ("order_id", "quantity", "unit_price")) and "CSV" in prompt:
        identity = "csv"
    elif "建筑日照" in prompt and "太阳" in prompt:
        identity = "html"
    else:
        return {"task_id": "custom-chat", "task_name": "自定义对话", "task_source": "custom", "task_kind": "custom"}
    return {"task_id": identity, "task_name": TASK_NAMES[identity], "task_source": "inferred", "task_kind": "task"}


def summary(record):
    result = {
        key: value
        for key, value in record.items()
        if key
        not in {
            "prompt",
            "csv",
            "request",
            "answer",
            "reasoning",
            "raw_usage",
            "quality",
            "note",
            "checks",
        }
    }
    result["prompt_preview"] = record["prompt"].strip().splitlines()[0][:60]
    result.update(task_info(record))
    result["experiment"] = record.get("experiment") or hashlib.sha256(record["prompt"].encode()).hexdigest()[:16]
    return result


class Connection(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=2000)
    api_key: str = Field(default="", max_length=2000)


class Attempt(BaseModel):
    model_id: str
    prompt: str = Field(min_length=1, max_length=100000)
    thinking: bool = False
    effort: str = "low"
    task_id: str = Field(default="", max_length=100)
    task_name: str = Field(default="", max_length=80)


class TaskAssignment(BaseModel):
    run_ids: list[str] = Field(min_length=1, max_length=500)
    task_id: str = Field(default="", max_length=100)
    name: str = Field(default="", max_length=80)


class CsvInput(BaseModel):
    csv: str = Field(max_length=200000)


@router.get("/config")
async def config():
    tasks = json.loads((HERE / "tasks.json").read_text(encoding="utf-8"))
    for task in tasks:
        filename = task.get("prompt_file")
        if filename:
            task["prompt"] = (HERE / filename).read_text(encoding="utf-8")
    return {
        "models": [
            dict(model, settings=public_profile(identity))
            for identity, model in MODELS.items()
        ],
        "tasks": tasks,
        "sample_csv": (HERE / "tasks/orders.csv").read_text(),
        "active": list(running),
    }


@router.post("/connections/{identity}")
async def connection(identity: str, body: Connection):
    if identity not in MODELS:
        raise ValueError("请选择课堂模型")
    base = body.base_url.strip().rstrip("/")
    url = urlsplit(base)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError(
            "服务地址应为 HTTP(S) API 根地址，不能包含密钥、查询参数或用户信息"
        )
    model = body.model.strip()
    if not model:
        raise ValueError("模型 ID 不能为空")
    profiles[identity].update(model=model, base_url=base)
    if body.api_key.strip():
        profiles[identity]["api_key"] = body.api_key.strip()
    return public_profile(identity)


@router.get("/lesson")
async def lesson():
    return FileResponse(HERE / "lesson-model-cost.html")


@router.get("/tasks/orders.csv")
async def sample_csv():
    return FileResponse(
        HERE / "tasks/orders.csv", filename="orders.csv", media_type="text/csv"
    )


@router.get("/vendor/three.js")
async def three_runtime():
    file = HERE.parent / "playground/dist/assets/classroom-three.js"
    if not file.is_file():
        raise HTTPException(
            503, "请先在 playground 目录运行 npm run build，生成本地 Three.js"
        )
    return FileResponse(
        file,
        media_type="application/javascript",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cross-Origin-Resource-Policy": "cross-origin",
            "Cache-Control": "no-cache",
        },
    )


@router.post("/reference")
async def reference(body: CsvInput):
    return inspect_orders(body.csv)


@router.get("/runs")
async def list_runs():
    ordered = sorted(
        records.values(), key=lambda record: record["started_at"], reverse=True
    )
    return {"items": [summary(record) for record in ordered]}


@router.post("/runs/assign-task")
async def assign_task(body: TaskAssignment):
    if body.task_id in TASK_NAMES:
        identity = body.task_id
        name = TASK_NAMES[identity]
    else:
        name = body.name.strip()
        if not name:
            raise ValueError("请填写任务名称")
        identity = "custom-" + hashlib.sha256(name.encode()).hexdigest()[:16]
    chosen = [get_record(run_id) for run_id in body.run_ids]
    if any(record["status"] == "RUNNING" for record in chosen):
        raise ValueError("请等待运行结束后再调整任务归类")
    for record in chosen:
        record.update(task_id=identity, task_name=name, task_source="manual", task_kind="task")
        save(record)
    return {"task_id": identity, "task_name": name}


@router.post("/runs")
async def start(body: Attempt):
    if body.model_id not in MODELS:
        raise ValueError("未知的课堂模型")
    if len(running) >= 3:
        raise ValueError("最多同时进行三次课堂尝试，请等待或取消一项")
    if not body.prompt.strip():
        raise ValueError("请填写提示词")
    if body.effort not in {"low", "high", "max"}:
        raise ValueError("请选择 low、high 或 max")
    profile = dict(profiles[body.model_id])
    if not profile["api_key"]:
        raise ValueError("请先在连接设置中保存 API Key")
    model = MODELS[body.model_id]
    provider = model["provider"]
    actual_model = profile["model"].lower().split("/")[-1]
    if actual_model.startswith("qwen"):
        provider = "qwen"
    elif actual_model.startswith("deepseek"):
        provider = "deepseek"
    content = body.prompt
    request = {
        "model": profile["model"],
        "messages": [{"role": "user", "content": content}],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if provider == "deepseek":
        # Without this argument, non-thinking requests default to only 8K.
        # Request the provider's documented maximum, not a classroom budget.
        request["max_tokens"] = 393216
        request["thinking"] = {"type": "enabled" if body.thinking else "disabled"}
        if body.thinking:
            request["reasoning_effort"] = body.effort
    else:
        request["max_tokens"] = 131072
        request["enable_thinking"] = body.thinking
    price = {
        "input": model["input"],
        "cached": model["cached"],
        "output": model["thinking_output"] if body.thinking else model["output"],
        "period": model["period"],
        "currency": "CNY",
        "unit_tokens": 1000000,
    }
    record = {
        "id": uuid4().hex,
        "model_id": body.model_id,
        "model_name": model["name"],
        "experiment": hashlib.sha256(content.encode()).hexdigest()[:16],
        "actual_model": profile["model"],
        "returned_model": None,
        "base_url": profile["base_url"],
        "prompt_preview": body.prompt.strip().splitlines()[0][:60],
        "prompt": body.prompt,
        "task_id": body.task_id or "custom-chat",
        "task_name": TASK_NAMES.get(body.task_id, body.task_name) if body.task_id and body.task_id != "custom-chat" else "自定义对话",
        "task_source": "task" if body.task_id and body.task_id != "custom-chat" else "custom",
        "task_kind": "task" if body.task_id and body.task_id != "custom-chat" else "custom",
        "request": request,
        "thinking": body.thinking,
        "effort": body.effort if provider == "deepseek" else None,
        "thinking_budget": None,
        "max_tokens": request.get("max_tokens"),
        "timeout": 600,
        "price": price,
        "started_at": now(),
        "finished_at": None,
        "status": "RUNNING",
        "duration": 0,
        "first_token": None,
        "first_answer": None,
        "usage": normalize_usage({}),
        "raw_usage": {},
        "cost": None,
        "reasoning": "",
        "answer": "",
        "finish_reason": None,
        "error": "",
        "revision": 0,
    }
    save(record)
    records[record["id"]] = record
    running[record["id"]] = asyncio.create_task(execute(record, profile))
    return {"id": record["id"]}


async def execute(record, profile):
    started = time.perf_counter()
    saved_at = started
    try:
        async with asyncio.timeout(record["timeout"]):
            async for packet in stream_model(
                profile["base_url"],
                profile["api_key"],
                record["request"],
                record["timeout"],
            ):
                if packet.get("error"):
                    raise ValueError(
                        "模型服务错误："
                        + json.dumps(packet["error"], ensure_ascii=False)
                    )
                elapsed = time.perf_counter() - started
                record["duration"] = elapsed
                record["returned_model"] = (
                    packet.get("model") or record["returned_model"]
                )
                if isinstance(packet.get("usage"), dict) and packet["usage"]:
                    record["raw_usage"].update(packet["usage"])
                    record["usage"] = normalize_usage(record["raw_usage"])
                    record["cost"] = estimate_cost(record["usage"], record["price"])
                for choice in packet.get("choices", []):
                    if choice.get("index", 0) != 0:
                        continue
                    delta = choice.get("delta") or choice.get("message") or {}
                    reasoning = response_text(delta.get("reasoning_content"))
                    answer = response_text(delta.get("content"))
                    if (reasoning or answer) and record["first_token"] is None:
                        record["first_token"] = elapsed
                    if answer and record["first_answer"] is None:
                        record["first_answer"] = elapsed
                    record["reasoning"] += reasoning
                    record["answer"] += answer
                    if choice.get("finish_reason"):
                        record["finish_reason"] = choice["finish_reason"]
                record["revision"] += 1
                if time.perf_counter() - saved_at >= 1:
                    save(record)
                    saved_at = time.perf_counter()
        if not record["finish_reason"]:
            raise ValueError("流已结束，但未收到完成原因；回复可能不完整")
        if record["finish_reason"] == "length":
            record["status"] = "TRUNCATED"
            record["error"] = (
                f"模型服务以 length 结束，回复未完整生成。本次请求 max_tokens={record['request'].get('max_tokens', '服务默认')}；可能达到网关输出上限或模型上下文长度限制。"
            )
        elif record["finish_reason"] != "stop":
            raise ValueError("本次回复未正常完成：" + record["finish_reason"])
        elif not record["answer"].strip():
            raise ValueError("模型未返回正式回复")
        else:
            record["status"] = "COMPLETED"
    except asyncio.CancelledError:
        record.update(
            status="CANCELLED", error="本次请求已取消；未返回的用量与费用保持未知"
        )
    except TimeoutError:
        record.update(
            status="FAILED", error=f"超过 {record['timeout']} 秒等待上限，已停止请求"
        )
    except Exception as error:
        message = str(error) or type(error).__name__
        message = message.replace(profile["api_key"], "[REDACTED]")
        record.update(status="FAILED", error=message[:1600])
    finally:
        record["finished_at"] = now()
        record["duration"] = time.perf_counter() - started
        record["revision"] += 1
        running.pop(record["id"], None)
        save(record)


@router.get("/runs/{identity}")
async def detail(identity: str):
    return public_record(get_record(identity))


@router.get("/runs/{identity}/events")
async def events(identity: str, request: Request):
    record = get_record(identity)

    async def updates():
        revision = -1
        while not await request.is_disconnected():
            if revision != record["revision"]:
                yield (
                    "data: "
                    + json.dumps(public_record(record), ensure_ascii=False)
                    + "\n\n"
                )
                revision = record["revision"]
            if record["status"] != "RUNNING":
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(
        updates(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{identity}/cancel")
async def cancel(identity: str):
    record = get_record(identity)
    task = running.get(identity)
    if task:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if record["status"] == "RUNNING":
            record.update(
                status="CANCELLED",
                error="本次请求已取消",
                finished_at=now(),
                revision=record["revision"] + 1,
            )
            running.pop(identity, None)
            save(record)
    return summary(record)


@router.delete("/runs/{identity}")
async def delete(identity: str):
    record = get_record(identity)
    if record["status"] == "RUNNING":
        raise ValueError("请先取消运行，再删除记录")
    (RECORDS / (record["id"] + ".json")).unlink(missing_ok=True)
    records.pop(identity)
    return {"deleted": identity}


def extract_html(answer):
    document = re.search(
        r"(?:<!doctype\s+html[^>]*>\s*)?<html\b[^>]*>[\s\S]*?</html\s*>",
        answer,
        re.IGNORECASE,
    )
    if document:
        return document.group(0)
    blocks = re.findall(r"```html[^\S\n]*\n([\s\S]*?)```", answer, re.IGNORECASE)
    candidates = blocks or [answer.strip()]
    for candidate in candidates:
        candidate = candidate.strip()
        if re.match(
            r"<(?:div|main|section|svg|body|style|canvas|article)\b",
            candidate,
            re.IGNORECASE,
        ) and re.search(r"</[a-z][a-z0-9:-]*\s*>\s*$", candidate, re.IGNORECASE):
            return (
                "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'></head><body>"
                + candidate
                + "</body></html>"
            )
    return None


def html_answer(record):
    answer = extract_html(record["answer"])
    if answer is None:
        raise ValueError("模型输出中没有完整的 HTML 文档或 HTML 代码块")
    return answer


def public_record(record):
    return dict(
        record,
        **task_info(record),
        html_available=record["status"] == "COMPLETED"
        and extract_html(record["answer"]) is not None,
    )


@router.get("/runs/{identity}/preview")
async def preview(identity: str, request: Request):
    record = get_record(identity)
    if record["status"] != "COMPLETED":
        raise ValueError("请等待回复正常完成后再打开预览")
    document = html_answer(record)
    resize_script = (HERE / "preview_resize.js").read_text(encoding="utf-8")
    resize_script = resize_script.replace("__CLASSROOM_RUN_ID__", json.dumps(identity))
    position = document.lower().rfind("</body")
    if position < 0:
        position = document.lower().rfind("</html")
    document = (
        document[:position]
        + "<script>"
        + resize_script
        + "</script>"
        + document[position:]
    )
    return HTMLResponse(
        document,
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'unsafe-inline' "
                + str(request.base_url).rstrip("/")
                + "/api/course/vendor/three.js; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'; sandbox allow-scripts"
            ),
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
        },
    )


@router.get("/runs/{identity}/download")
async def download(identity: str, format: str = "json"):
    record = get_record(identity)
    if format == "html":
        document = html_answer(record)
        runtime = HERE.parent / "playground/dist/assets/classroom-three.js"
        if not runtime.is_file():
            raise HTTPException(
                503, "请先在 playground 目录运行 npm run build，生成本地 Three.js"
            )
        document = re.sub(
            r"""(?:https?://[^/\s"']+)?/api/course/vendor/three\.js""",
            "./assets/three.js",
            document,
        )
        archive = BytesIO()
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as package:
            package.writestr("index.html", document)
            package.write(runtime, "assets/three.js")
            license_file = HERE.parent / "playground/node_modules/three/LICENSE"
            if license_file.is_file():
                package.write(license_file, "assets/THREE-LICENSE.txt")
        return Response(
            archive.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="classroom-{identity[:8]}.zip"'
            },
        )
    if format != "json":
        raise ValueError("请选择 JSON 或 HTML")
    return FileResponse(
        RECORDS / (record["id"] + ".json"), filename=f"classroom-{identity[:8]}.json"
    )


async def shutdown():
    for identity in list(running):
        await cancel(identity)
