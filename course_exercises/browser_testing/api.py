"""Persistent browser exercises and model-assisted test / application editing."""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .runner import execute_suite, parse_script

HERE = Path(__file__).resolve().parent
SESSIONS = HERE / "sessions"
router = APIRouter(prefix="/api/course/browser", tags=["browser-classroom"])
sessions = {}
pending = {}
DEFAULT_INTENT = """添加交通费 12.50 元，再添加午餐费 7.50 元。检查两条记录都存在，合计为 ¥20.00。
删除交通费后，只剩午餐费，合计为 ¥7.50。
不填写费用名称，输入金额 10 并添加：应提示“请输入费用名称”，不能新增记录。
请将以上要求写成三个独立用例，每个用例从空白清单开始。"""
REQUIREMENTS = """报销清单：添加名称非空、金额大于零的费用；以两位小数展示金额；
合计为所有费用金额之和；删除指定费用后更新列表与合计；无效输入提示错误且不新增费用。
页面使用中文；保留费用名称、金额标签，添加费用按钮，以及现有 data-testid 和删除按钮 accessible name。
数据只保存在页面内存，刷新清空。不使用外部依赖、网络、存储或额外文件。"""
SCRIPT_RULES = """只输出 Python 代码，不作解释。运行环境提供 page、expect、APP_URL。
可选导入 from playwright.async_api import expect, Page。
只定义 async def test_名称(page):，每个测试必须首先 await page.goto(APP_URL)。
每个函数只写逐行 await 调用，不使用变量、循环、分支、装饰器、fixture、其他 import。
支持 page 和定位器的 get_by_role/get_by_label/get_by_text/get_by_test_id/locator；定位器还支持 nth 和 filter(has_text="文本")。
支持 fill、click、press、check、uncheck、select_option。
支持 await expect(定位器).to_have_text/to_contain_text/to_have_count/to_have_value/to_be_visible/to_be_hidden/to_be_enabled/to_be_disabled。
参数只能是文本、数字、布尔值或列表；不使用正则表达式、timeout、evaluate、截图、文件或网络操作。
每个测试至少有一个业务断言。总共不超过 12 个用例，每个用例不超过 60 步。
例如：
async def test_添加费用(page):
    await page.goto(APP_URL)
    await page.get_by_label("费用名称", exact=True).fill("交通费")
    await page.get_by_label("金额", exact=True).fill("12.50")
    await page.get_by_role("button", name="添加费用", exact=True).click()
    await expect(page.get_by_test_id("total")).to_have_text("¥12.50")
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def save(session):
    folder = SESSIONS / session["id"]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "session.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)


def interrupt_cases(execution, message):
    for case in execution["cases"]:
        if case["status"] == "RUNNING":
            case.update(status="INTERRUPTED", error=message)
        for step in case["steps"]:
            if step["status"] == "RUNNING":
                step.update(status="INTERRUPTED", error=message)


def get_session(identity):
    if not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise HTTPException(404, "找不到练习")
    if identity in sessions:
        return sessions[identity]
    path = SESSIONS / identity / "session.json"
    if not path.is_file():
        raise HTTPException(404, "找不到练习")
    session = json.loads(path.read_text(encoding="utf-8"))
    if session["status"] != "IDLE":
        session.update(status="IDLE", error="服务已重启，上一次操作已中断")
        for execution in session["executions"]:
            if execution["status"] == "RUNNING":
                execution.update(status="INTERRUPTED", error="服务已重启")
                interrupt_cases(execution, "服务已重启")
        save(session)
    sessions[identity] = session
    return session


def public_session(session):
    from .. import api as course

    result = dict(session)
    result["executions"] = []
    for execution in session["executions"]:
        snapshot = dict(execution)
        snapshot.pop("html")
        result["executions"].append(snapshot)
    result["calls"] = []
    for call in session["calls"]:
        record = course.records.get(call["id"])
        if record:
            result["calls"].append(dict(course.summary(record), action=call["action"]))
    return result


class Action(BaseModel):
    action: str
    model_id: str = "deepseek-flash"
    thinking: bool = False
    effort: str = "low"
    intent: str = Field(default="", max_length=20000)
    script: str = Field(default="", max_length=60000)


@router.get("/sessions")
async def list_sessions():
    items = []
    for path in SESSIONS.glob("*/session.json"):
        session = get_session(path.parent.name)
        items.append({
            "id": session["id"],
            "created_at": session["created_at"],
            "revision": session["revision"],
            "status": session["status"],
        })
    return {"items": sorted(items, key=lambda item: item["created_at"], reverse=True)}


@router.post("/sessions")
async def create_session():
    session = {
        "id": uuid4().hex,
        "created_at": now(),
        "status": "IDLE",
        "error": "",
        "intent": DEFAULT_INTENT,
        "requirements": REQUIREMENTS,
        "script": "",
        "html": (HERE / "expense.html").read_text(encoding="utf-8"),
        "revision": 0,
        "calls": [],
        "executions": [],
    }
    sessions[session["id"]] = session
    save(session)
    return public_session(session)


@router.get("/sessions/{identity}")
async def detail(identity: str):
    return public_session(get_session(identity))


@router.get("/sessions/{identity}/files/{filename}")
async def artifact(identity: str, filename: str):
    session = get_session(identity)
    allowed = set()
    for execution in session["executions"]:
        for case in execution["cases"]:
            if case.get("trace"):
                allowed.add(case["trace"])
            for step in case["steps"]:
                if step.get("screenshot"):
                    allowed.add(step["screenshot"])
    if filename not in allowed:
        raise HTTPException(404, "找不到执行产物")
    return FileResponse(SESSIONS / identity / filename)


@router.post("/sessions/{identity}/actions")
async def start_action(identity: str, body: Action):
    session = get_session(identity)
    if identity in pending:
        raise HTTPException(409, "请等待当前操作完成")
    if body.action not in {"generate", "execute", "repair"}:
        raise ValueError("未知操作")
    if len(pending) >= 3:
        raise ValueError("最多同时进行三个浏览器练习操作")
    if body.action == "generate" and not body.intent.strip():
        raise ValueError("请填写测试意图")
    if body.action == "execute":
        parse_script(body.script)
    if body.action == "repair":
        if not session["executions"] or session["executions"][-1]["status"] != "FAILED":
            raise ValueError("请先执行测试，获得失败反馈")
        execution = session["executions"][-1]
        if not any(case["status"] == "FAILED" for case in execution["cases"]):
            raise ValueError("浏览器启动或执行环境错误不能用于修复应用")
        if execution["revision"] != session["revision"] or execution["script"] != body.script:
            raise ValueError("应用或脚本已变化，请先重新执行测试")
    if body.action in {"generate", "repair"}:
        from .. import api as course

        if (
            body.model_id not in course.profiles
            or not course.profiles[body.model_id]["api_key"]
        ):
            raise ValueError("请先设置模型连接和 API Key")
    statuses = {
        "generate": "GENERATING",
        "execute": "EXECUTING",
        "repair": "REPAIRING",
    }
    session.update(status=statuses[body.action], error="")
    if body.action == "generate":
        session["intent"] = body.intent.strip()
    if body.action == "execute":
        session["script"] = body.script
    save(session)
    pending[identity] = asyncio.create_task(perform(session, body))
    return public_session(session)


def code_block(answer, language):
    blocks = re.findall(
        r"```(?:" + language + r")?\s*\n([\s\S]*?)```",
        answer,
        re.IGNORECASE,
    )
    return blocks[0].strip() if blocks else answer.strip()


async def perform(session, body):
    from .. import api as course

    model_task = None
    execution = None
    try:
        if body.action == "execute":
            execution = {
                "id": uuid4().hex,
                "started_at": now(),
                "finished_at": None,
                "revision": session["revision"],
                "script": session["script"],
                "intent": session["intent"],
                "script_hash": hashlib.sha256(session["script"].encode()).hexdigest(),
                "html": session["html"],
                "status": "RUNNING",
                "cases": [],
                "duration": 0,
                "error": "",
            }
            session["executions"].append(execution)
            save(session)
            await execute_suite(
                session, execution, SESSIONS / session["id"], save,
            )
            execution["finished_at"] = now()
            return
        if body.action == "generate":
            prompt = (
                "你是浏览器功能测试工程师。根据用户验收意图生成测试，验证正确业务行为，不能迎合源码中的缺陷。\n"
                + SCRIPT_RULES + "\n业务要求：\n" + REQUIREMENTS
                + "\n测试意图：\n" + session["intent"] + "\n页面源码（仅用于定位元素）：\n" + session["html"]
            )
        else:
            failed = session["executions"][-1]
            feedback = {"cases": failed["cases"], "error": failed["error"]}
            prompt = (
                "修复以下单文件 HTML 应用，使固定的测试通过。只输出完整 HTML，不解释。"
                "不得修改、绕过测试或检测测试环境；修复真实业务逻辑，保留原有功能、标签和定位契约。"
                "所有 CSS、JavaScript 内联，不使用外部资源。\n业务要求：\n" + REQUIREMENTS
                + "\n用户测试意图：\n" + failed["intent"] + "\n固定测试：\n" + failed["script"]
                + "\n失败反馈：\n" + json.dumps(feedback, ensure_ascii=False)
                + "\n当前源码：\n" + session["html"]
            )
        started = await course.start(course.Attempt(
            model_id=body.model_id,
            prompt=prompt,
            thinking=body.thinking,
            effort=body.effort,
        ))
        identity = started["id"]
        model_task = course.running[identity]
        session["calls"].append({"id": identity, "action": body.action})
        save(session)
        await model_task
        record = course.records[identity]
        if record["status"] != "COMPLETED":
            raise ValueError(record["error"] or "模型回复未完整生成")
        if body.action == "generate":
            script = code_block(record["answer"], "python")
            parse_script(script)
            session["script"] = script
        else:
            html = code_block(record["answer"], "html")
            if "<html" not in html.lower() or "</html>" not in html.lower():
                raise ValueError("模型未返回完整 HTML；原应用保持不变")
            session["html"] = html
            session["revision"] += 1
    except asyncio.CancelledError:
        if model_task is not None and not model_task.done():
            model_task.cancel()
        session["error"] = "操作已取消"
        if execution:
            execution.update(status="INTERRUPTED", error="操作已取消", finished_at=now())
            interrupt_cases(execution, "操作已取消")
    except Exception as error:
        session["error"] = str(error)[:6000] or type(error).__name__
        if execution:
            execution.update(status="FAILED", error=session["error"], finished_at=now())
            interrupt_cases(execution, session["error"])
    finally:
        session["status"] = "IDLE"
        pending.pop(session["id"], None)
        save(session)


@router.post("/sessions/{identity}/cancel")
async def cancel(identity: str):
    get_session(identity)
    task = pending.get(identity)
    if task:
        task.cancel()
        await task
    return public_session(get_session(identity))


async def shutdown():
    tasks = list(pending.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
