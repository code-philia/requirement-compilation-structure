"""Local requirement workspaces, document operations and a streaming tool agent."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
import yaml

from . import agent
from .document import apply_operation, inspect_document, markdown_document, validate_document, walk, yaml_document

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SESSIONS = HERE / "sessions"
router = APIRouter(prefix="/api/course/requirements", tags=["requirements-classroom"])
sessions = {}
running = {}


def now():
    return datetime.now(timezone.utc).isoformat()


def save(session):
    folder = SESSIONS / session["id"]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "session.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)


def write_input(session):
    folder = SESSIONS / session["id"] / "input"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "requirements.yaml"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(yaml_document(session["tree"]), encoding="utf-8")
    temporary.replace(target)
    if not session["input_assets"]:
        return
    source_root = (ROOT / "input").resolve()
    for node in walk(session["tree"]):
        for image in node["description"]["image"]:
            source = (source_root / image["reference"]).resolve()
            if not source.is_relative_to(source_root) or not source.is_file():
                continue
            destination = folder / image["reference"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)


def quality(session):
    report = inspect_document(session["tree"])
    folder = SESSIONS / session["id"] / "input"
    for node in walk(session["tree"]):
        for image in node["description"]["image"]:
            if not (folder / image["reference"]).is_file():
                report["issues"].append({"node_id": node["id"], "message": f"参考图文件缺失：{image['reference']}；需放入编译输入目录"})
    return report


def interrupted_context(turn, message):
    completed = []
    for tool in turn["tools"]:
        if tool["status"] == "COMPLETED":
            completed.append(tool["name"] + "：" + tool["result"])
    return [
        {"role": "user", "content": turn["user"]},
        {"role": "assistant", "content": "本轮未完成：" + message + "\n已执行的操作：\n" + "\n".join(completed) + "\n后续以当前需求树为准，未完成事项仍需核对。"},
    ]


def get_session(identity):
    if not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise HTTPException(404, "找不到需求项目")
    if identity in sessions:
        return sessions[identity]
    path = SESSIONS / identity / "session.json"
    if not path.is_file():
        raise HTTPException(404, "找不到需求项目")
    session = json.loads(path.read_text(encoding="utf-8-sig"))
    if session["status"] != "IDLE":
        session.update(status="IDLE", phase="", error="服务已重启，上次对话中断；已保存的文档修改仍保留")
        interrupted_turn = None
        for turn in session["turns"]:
            if turn["status"] == "RUNNING":
                interrupted_turn = turn
                turn.update(status="INTERRUPTED", error=session["error"])
                for tool in turn["tools"]:
                    if tool["status"] == "RUNNING":
                        tool.update(status="FAILED", result="服务已重启，请核对当前文档")
        # Do not replay a partially assembled tool protocol on the next request.
        if interrupted_turn:
            start = len(session["history"])
            for index in range(len(session["history"]) - 1, -1, -1):
                if session["history"][index]["role"] == "user":
                    start = index
                    break
            session["history"] = session["history"][:start]
            session["history"].extend(interrupted_context(interrupted_turn, session["error"]))
        for record in session["compactions"]:
            if record["status"] == "RUNNING":
                record["status"] = "INTERRUPTED"
        save(session)
    sessions[identity] = session
    return session


def public(session):
    return {
        "id": session["id"], "created_at": session["created_at"],
        "name": session["tree"]["name"], "tree": session["tree"],
        "revision": session["revision"], "status": session["status"],
        "phase": session["phase"], "error": session["error"],
        "turns": session["turns"], "changes": session["changes"],
        "summary": session["summary"], "compactions": session["compactions"],
        "context_chars": agent.context_chars(session), "context_limit": agent.CONTEXT_LIMIT,
        "can_undo": bool(session["undo"]), "quality": quality(session),
        "markdown": markdown_document(session["tree"]), "yaml": yaml_document(session["tree"]),
        "input_path": str((SESSIONS / session["id"] / "input").relative_to(ROOT)),
    }


def commit(session, document, action, node_id, source, *, undo=True):
    document = validate_document(document)
    if document == session["tree"]:
        return
    if undo:
        session["undo"].append(deepcopy(session["tree"]))
        session["undo"] = session["undo"][-20:]
    session["tree"] = document
    session["revision"] += 1
    session["changes"].append({"revision": session["revision"], "action": action, "node_id": node_id, "source": source, "created_at": now()})
    write_input(session)
    save(session)


class Create(BaseModel):
    template: str = "blank"


class Mutation(BaseModel):
    revision: int
    operation: str
    arguments: dict = Field(default_factory=dict)


class Import(BaseModel):
    revision: int
    text: str = Field(min_length=1, max_length=1000000)


class Chat(BaseModel):
    model_id: str = "deepseek-flash"
    message: str = Field(default="", max_length=30000)
    thinking: bool = False
    effort: str = "low"
    compact: bool = False
    node_id: str = ""


@router.get("/sessions")
async def list_sessions():
    items = []
    for path in SESSIONS.glob("*/session.json"):
        session = get_session(path.parent.name)
        items.append({"id": session["id"], "name": session["tree"]["name"], "created_at": session["created_at"]})
    return {"items": sorted(items, key=lambda item: item["created_at"], reverse=True)}


@router.post("/sessions")
async def create(body: Create):
    if body.template == "input":
        tree = yaml.safe_load((ROOT / "input/requirements.yaml").read_text(encoding="utf-8-sig"))
    elif body.template == "blank":
        tree = {"id": "ROOT", "name": "我的需求项目", "description": {"text": ""}, "scenarios": [], "children": []}
    else:
        raise ValueError("请选择空白项目或当前 input 示例")
    session = {
        "id": uuid4().hex, "created_at": now(), "tree": validate_document(tree),
        "revision": 0, "status": "IDLE", "phase": "", "error": "",
        "turns": [], "history": [], "summary": "", "compactions": [],
        "undo": [], "changes": [], "input_assets": body.template == "input",
    }
    write_input(session)
    save(session)
    sessions[session["id"]] = session
    return public(session)


@router.get("/sessions/{identity}")
async def detail(identity: str):
    return public(get_session(identity))


def editable(session, revision):
    if session["id"] in running:
        raise HTTPException(409, "请先停止智能体或等待本轮结束，再编辑文档")
    if session["revision"] != revision:
        raise HTTPException(409, "文档已更新，请基于最新版本重试")


@router.post("/sessions/{identity}/mutations")
async def mutate(identity: str, body: Mutation):
    session = get_session(identity)
    editable(session, body.revision)
    if body.operation == "undo":
        if not session["undo"]:
            raise ValueError("没有可撤销的修改")
        document = session["undo"].pop()
        commit(session, document, "undo", document["id"], "manual", undo=False)
    else:
        try:
            document, node_id = apply_operation(session["tree"], body.operation, body.arguments)
        except (KeyError, TypeError) as error:
            raise ValueError("操作参数不完整，请检查节点信息") from error
        commit(session, document, body.operation, node_id, "manual")
    return public(session)


@router.post("/sessions/{identity}/import")
async def import_document(identity: str, body: Import):
    session = get_session(identity)
    editable(session, body.revision)
    try:
        document = yaml.safe_load(body.text)
    except yaml.YAMLError as error:
        raise ValueError("文档不是有效 YAML / JSON，请检查缩进与字段") from error
    commit(session, document, "import", "ROOT", "manual")
    return public(session)


@router.get("/sessions/{identity}/export/{format}")
async def export(identity: str, format: str):
    session = get_session(identity)
    if format == "yaml":
        return Response(yaml_document(session["tree"]), media_type="application/yaml; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="requirements.yaml"'})
    if format == "markdown":
        return Response(markdown_document(session["tree"]), media_type="text/markdown", headers={"Content-Disposition": 'attachment; filename="requirements.md"'})
    if format != "zip":
        raise ValueError("请选择 yaml、markdown 或 zip")
    folder = SESSIONS / identity / "input"
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("requirements.yaml", yaml_document(session["tree"]))
        added = set()
        for node in walk(session["tree"]):
            for image in node["description"]["image"]:
                reference = image["reference"]
                file = folder / reference
                if reference not in added and file.is_file():
                    archive.write(file, reference)
                    added.add(reference)
    return Response(buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="requirement-input.zip"'})


@router.post("/sessions/{identity}/chat")
async def chat(identity: str, body: Chat):
    from .. import api as course

    session = get_session(identity)
    if identity in running:
        raise HTTPException(409, "请等待当前对话完成")
    if len(running) >= 3:
        raise ValueError("最多同时运行三个需求智能体")
    if body.model_id not in course.profiles or not course.profiles[body.model_id]["api_key"]:
        raise ValueError("请先设置模型连接和 API Key")
    if body.effort not in {"low", "high", "max"}:
        raise ValueError("请选择有效的思考强度")
    if not body.compact and not body.message.strip():
        raise ValueError("请填写消息")
    session.update(status="RUNNING", phase="准备对话", error="")
    profile = dict(course.profiles[body.model_id])
    model = dict(course.MODELS[body.model_id])
    running[identity] = asyncio.create_task(run_agent(session, body, profile, model))
    save(session)
    return public(session)


async def run_agent(session, body, profile, model):
    turn = None
    history_start = len(session["history"])
    try:
        async with asyncio.timeout(1200):
            if body.compact or agent.context_chars(session) + len(body.message) > agent.CONTEXT_LIMIT:
                await agent.compact(session, profile, model, lambda: save(session), now)
            if body.compact:
                return
            history_start = len(session["history"])
            turn = {
                "id": uuid4().hex, "user": body.message.strip(), "model": profile["model"],
                "answer": "", "reasoning": "", "tools": [], "usage": [],
                "started_at": now(), "status": "RUNNING", "error": "",
            }
            session["turns"].append(turn)
            session["history"].append({"role": "user", "content": body.message.strip()})
            save(session)
            for _ in range(12):
                session["phase"] = "模型正在分析需求"
                if turn["answer"]:
                    turn["answer"] += "\n\n"
                system = agent.system_message(session)
                if body.node_id:
                    system["content"] += "\n用户在界面选中的节点（用于理解指代）：" + body.node_id
                message = await agent.completion(
                    profile, model, [system, *session["history"]],
                    turn, lambda: save(session), thinking=body.thinking, effort=body.effort, tools=True,
                )
                session["history"].append(message)
                calls = message.get("tool_calls", [])
                if not calls:
                    turn["status"] = "COMPLETED"
                    return
                for call in calls:
                    name = call["function"]["name"]
                    session["phase"] = "正在维护需求树 · " + name
                    entry = {"id": call["id"], "name": name, "status": "RUNNING", "arguments": {}, "result": ""}
                    turn["tools"].append(entry)
                    save(session)
                    try:
                        arguments = json.loads(call["function"]["arguments"])
                        if not isinstance(arguments, dict):
                            raise ValueError("工具参数必须是 JSON 对象")
                        entry["arguments"] = arguments
                        if name == "read_document":
                            result = {"revision": session["revision"], "document": session["tree"], "quality": quality(session)}
                        elif name == "read_node":
                            node = next((item for item in walk(session["tree"]) if item["id"] == arguments["node_id"]), None)
                            if node is None:
                                raise ValueError("节点不存在")
                            result = {"revision": session["revision"], "node": node}
                        else:
                            document, node_id = apply_operation(session["tree"], name, arguments)
                            commit(session, document, name, node_id, "agent")
                            result = {"revision": session["revision"], "node_id": node_id, "quality": quality(session)}
                        entry.update(status="COMPLETED", result=f"已完成 · 修订 {session['revision']}")
                    except (ValueError, KeyError, TypeError, RecursionError) as error:
                        result = {"error": str(error), "revision": session["revision"]}
                        entry.update(status="FAILED", result=str(error))
                    session["history"].append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)})
                    save(session)
            raise ValueError("本轮已执行多轮工具交互，请缩小范围继续；已保存的修改仍保留")
    except BaseException as error:
        if isinstance(error, asyncio.CancelledError):
            message = "已停止对话，已保存的修改仍保留，可撤销"
        elif isinstance(error, TimeoutError):
            message = "本轮等待超时，已保存的修改仍保留，请继续或缩小范围"
        else:
            message = (str(error) or type(error).__name__).replace(profile["api_key"], "[REDACTED]")[:4000]
        session["error"] = message
        if turn:
            turn.update(status="INTERRUPTED" if isinstance(error, asyncio.CancelledError) else "FAILED", error=message)
            session["history"] = session["history"][:history_start]
            session["history"].extend(interrupted_context(turn, message))
        if not isinstance(error, (Exception, asyncio.CancelledError)):
            raise
    finally:
        session.update(status="IDLE", phase="")
        running.pop(session["id"], None)
        save(session)


@router.post("/sessions/{identity}/cancel")
async def cancel(identity: str):
    session = get_session(identity)
    task = running.get(identity)
    if task:
        task.cancel()
        await task
    return public(session)


async def shutdown():
    tasks = list(running.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
