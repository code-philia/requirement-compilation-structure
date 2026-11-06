"""Persistent browser exercises and model-assisted test / application editing."""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .runner import execute_suite, parse_script
from .edits import EDIT_RULES, apply_edits, parse_proposal

HERE = Path(__file__).resolve().parent
SESSIONS = HERE / "sessions"
router = APIRouter(prefix="/api/course/browser", tags=["browser-classroom"])
sessions = {}
pending = {}
live = {}
DEFAULT_INTENT = """为费用报销工作台编写独立的 Playwright 测试用例：
添加交通费 12.50 元，再添加午餐费 7.50 元。检查两条记录都存在，全部费用合计为 ¥20.00。
删除交通费后，只剩午餐费，合计为 ¥7.50。
不填写费用名称，输入金额 10 并添加：应提示“请输入费用名称”，不能新增记录。
增加分类筛选测试：只显示选定分类，筛选不影响全部费用合计。
增加提交测试：无发票的费用不能提交；补全发票后可提交，已提交费用不能编辑或删除，但可撤回。
每个用例从空白清单开始，自行录入所需数据，不使用示例按钮。"""
REQUIREMENTS = """费用报销工作台：费用包含名称、金额、分类（交通/餐饮/住宿/其他）、日期、发票状态。
名称不能为空，金额大于零且最多两位小数，日期必填。默认今天、交通分类、有发票。
金额按分保存，显示两位小数。全部费用合计为所有记录金额之和，不受筛选影响。
搜索、分类与状态筛选可以组合，筛选结果合计仅统计可见记录。
待提交费用可以编辑、删除；勾选费用可批量提交。任何选中费用缺发票时，整批不能提交。
已提交费用不能编辑或删除，可以撤回；已提交金额、待提交笔数和选择状态要同步更新。
保留现有中文标签、data-testid、按钮名称。添加费用后清空表单，恢复默认分类、日期、有发票。
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
    result["messages"] = []
    for call in session["calls"]:
        record = course.records.get(call["id"])
        if record:
            result["calls"].append(dict(course.summary(record), action=call["action"]))
            result["messages"].append({
                "id": call["id"],
                "action": call["action"],
                "created_at": record["started_at"],
                "user": call.get("user_text", "生成测试" if call["action"] == "generate" else "修复应用"),
                "answer": record["answer"],
                "reasoning": record["reasoning"],
                "status": record["status"],
                "error": record["error"],
                "model": record["model_name"],
                "proposal": call.get("proposal"),
                "proposal_error": call.get("proposal_error", ""),
                "applied_revision": call.get("applied_revision"),
            })
    return result


class Action(BaseModel):
    action: str
    model_id: str = "deepseek-flash"
    thinking: bool = False
    effort: str = "low"
    intent: str = Field(default="", max_length=20000)
    script: str = Field(default="", max_length=60000)
    message: str = Field(default="", max_length=20000)
    feedback: str = Field(default="", max_length=50000)


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


@router.post("/sessions/{identity}/replies/{reply_id}/apply")
async def apply_reply(identity: str, reply_id: str):
    session = get_session(identity)
    if identity in pending:
        raise HTTPException(409, "请等待当前操作完成")
    call = next((item for item in session["calls"] if item["id"] == reply_id), None)
    if call is None or not call.get("proposal"):
        raise ValueError("这条回复没有可应用的修改列表")
    if call.get("applied_revision") is not None:
        raise ValueError("这批修改已应用，请勿重复应用")
    if call["base_revision"] != session["revision"]:
        raise HTTPException(409, "应用代码已变化，请模型基于当前代码重新提出修改")
    proposal = parse_proposal(json.dumps(call["proposal"], ensure_ascii=False))
    html = apply_edits(session["html"], proposal["edits"])
    session["html"] = html
    session["revision"] += 1
    session["error"] = ""
    call["applied_revision"] = session["revision"]
    save(session)
    return public_session(session)


@router.get("/sessions/{identity}/live")
async def live_preview(identity: str, request: Request):
    get_session(identity)

    async def frames():
        previous = None
        keepalive = 0
        while not await request.is_disconnected():
            state = live.get(identity, {"execution_id": "", "sequence": 0, "frame": "", "status": "IDLE", "step": "", "case": ""})
            revision = (state["execution_id"], state["sequence"])
            if revision != previous:
                yield "data: " + json.dumps(state, ensure_ascii=False) + "\n\n"
                previous = revision
            keepalive += 1
            if keepalive >= 60:
                yield ": keepalive\n\n"
                keepalive = 0
            await asyncio.sleep(0.15)

    return StreamingResponse(
        frames(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    if body.action not in {"chat", "generate", "execute", "repair"}:
        raise ValueError("未知操作")
    if len(pending) >= 3:
        raise ValueError("最多同时进行三个浏览器练习操作")
    if body.action == "generate" and not body.intent.strip():
        raise ValueError("请填写测试意图")
    if body.action == "chat" and not body.message.strip():
        raise ValueError("请填写消息")
    if body.action == "execute":
        parse_script(body.script)
    if body.action == "repair":
        if not body.feedback.strip():
            raise ValueError("请粘贴测试反馈，或填入最近一次执行结果")
    if body.action in {"chat", "generate", "repair"}:
        from .. import api as course

        if (
            body.model_id not in course.profiles
            or not course.profiles[body.model_id]["api_key"]
        ):
            raise ValueError("请先设置模型连接和 API Key")
    statuses = {
        "chat": "CHATTING",
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
            state = {
                "execution_id": execution["id"], "sequence": 0,
                "frame": "", "step": "正在启动浏览器", "case": "",
                "status": "RUNNING",
            }
            live[session["id"]] = state

            def publish(frame=None, step=None, case=None):
                if frame is not None:
                    state["frame"] = frame
                if step is not None:
                    state["step"] = step
                if case is not None:
                    state["case"] = case
                state["sequence"] += 1

            await execute_suite(
                session, execution, SESSIONS / session["id"], save, publish,
            )
            execution["finished_at"] = now()
            return
        if body.action == "chat":
            conversation = []
            for call in session["calls"][-6:]:
                record = course.records.get(call["id"])
                if record is None:
                    continue
                conversation.append("用户：\n" + call.get("user_text", call["action"]))
                conversation.append("助手：\n" + record["answer"])
            feedback = body.feedback.strip()
            if not feedback and session["executions"]:
                latest = session["executions"][-1]
                feedback = json.dumps({"cases": latest["cases"], "error": latest["error"]}, ensure_ascii=False)
            prompt = (
                "你是浏览器自动化课堂助手，与学员对话，按要求解释或编写测试。"
                "解释使用中文 Markdown。测试代码使用 python 代码块。"
                "用户要求修改应用时，按照下方 edit_file 协议返回修改列表，由用户点击 Apply。"
                "测试验证业务要求，不迎合应用中的缺陷。\n" + EDIT_RULES
                + SCRIPT_RULES.replace("只输出 Python 代码，不作解释。", "编写测试时遵循以下语法：")
                + "\n业务要求：\n" + REQUIREMENTS
                + "\n当前应用源码（用于定位元素）：\n" + session["html"]
                + "\n当前测试脚本：\n" + (body.script.strip() or session["script"])
                + "\n测试反馈：\n" + feedback
                + "\n最近对话：\n" + "\n\n".join(conversation)
                + "\n用户本次消息：\n" + body.message.strip()
            )
            user_text = body.message.strip()
        elif body.action == "generate":
            prompt = (
                "你是浏览器功能测试工程师。根据用户验收意图生成测试，验证正确业务行为，不能迎合源码中的缺陷。\n"
                + SCRIPT_RULES + "\n业务要求：\n" + REQUIREMENTS
                + "\n测试意图：\n" + session["intent"] + "\n页面源码（仅用于定位元素）：\n" + session["html"]
            )
            user_text = session["intent"]
        else:
            fixed_script = body.script.strip() or session["script"]
            prompt = (
                "修复以下单文件 HTML 应用，使固定的测试通过。只返回 edit_file 修改列表 JSON。"
                "不得修改、绕过测试或检测测试环境；修复真实业务逻辑，保留原有功能、标签和定位契约。"
                "所有 CSS、JavaScript 内联，不使用外部资源。\n" + EDIT_RULES
                + "\n业务要求：\n" + REQUIREMENTS
                + "\n固定测试：\n" + fixed_script
                + "\n失败反馈：\n" + body.feedback.strip()
                + "\n当前源码：\n" + session["html"]
            )
            user_text = "请根据以下测试反馈修复应用，保持测试不变：\n\n" + body.feedback.strip()
        started = await course.start(course.Attempt(
            model_id=body.model_id,
            prompt=prompt,
            thinking=body.thinking,
            effort=body.effort,
            task_id="browser",
            task_name="浏览器测试",
        ))
        identity = started["id"]
        model_task = course.running[identity]
        call = {
            "id": identity,
            "action": body.action,
            "user_text": user_text,
            "base_revision": session["revision"],
        }
        session["calls"].append(call)
        save(session)
        await model_task
        record = course.records[identity]
        if record["status"] != "COMPLETED":
            raise ValueError(record["error"] or "模型回复未完整生成")
        if body.action == "generate":
            script = code_block(record["answer"], "python")
            parse_script(script)
            session["script"] = script
        elif body.action == "repair" or '"edits"' in record["answer"]:
            try:
                proposal = parse_proposal(record["answer"])
                apply_edits(session["html"], proposal["edits"])
                call["proposal"] = proposal
            except ValueError as error:
                call["proposal_error"] = str(error)
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
        if execution is not None:
            state = live.get(session["id"])
            if state and state["execution_id"] == execution["id"]:
                state["status"] = execution["status"]
                state["sequence"] += 1
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
