"""Native tool calls and loss-aware conversation compaction for authoring."""

import json
import time
from uuid import uuid4

from ..model_client import response_text
from ..model_client import stream_model
from .document import tool_definitions, yaml_document

CONTEXT_LIMIT = 48000
SYSTEM = """你是面向无编程背景学员的需求分析助手，通过工具维护需求树。
先理解用户、目标、范围，再从模块大纲逐步完善叶子需求。信息不足时提问，或明确标记“待确认”，
不要把猜测当作已确认事实，不主动扩展业务范围。用中文解释修改和待确认事项。
根节点描述项目目标和不做什么；父节点组织模块，叶子描述可独立验收的业务行为。
叶子需要正常、异常、边界或权限等适用场景；每步写清 Given 前置、When 操作、Then 可观察结果，
必要时说明数据是否变化、刷新后状态、错误消息、规则优先级。不要默认技术实现方案。
格式与 input/requirements.yaml 相同：
id: ROOT
name: 项目名称
description: {text: 项目目标、用户、范围}
scenarios: []
children:
  - id: REQ-1
    name: 独立业务行为
    description: {text: 输入、业务规则、输出、边界}
    scenarios:
      - id: SCN-REQ-1-01
        name: 场景名称
        steps:
          - id: STEP-REQ-1-01-01
            Given: 明确的前置条件
            When: 用户操作
            Then: 可核对的结果
            references: []
    children: []
可选 description.image 是 {id, reference, page} 的列表，reference 是相对路径；不要编造已有图片。
ID 必须全局唯一，已有 ID 保持不变。引用写作 \\ref[requirement](REQ-1) 或 \\ref[image](IMG-1)。
真正修改文档必须调用工具，不能只在回复中声称修改成功。工具报错后据错误修正，不能掩盖失败。
首次起草或用户明确要求整体替换时可 replace_document；其他调整优先 add_node/update_node/move_node。
用户只要求讨论、审阅或提问时不要改树；删除仅在明确要求下执行。保留未涉及的节点与场景。
文档大纲允许先没有场景，明确指出待完善项；不要为了让检查通过而编造验收结果。
完整文档以工具保存后的树为准，用户可导出 YAML；需要展示完整文本时返回与已保存内容一致的 YAML。
每次调用工具后依据其结果继续工作，最后用简短文字说明变更、关键规则和下一步建议。
"""


def context_chars(session):
    return len(session["summary"]) + len(json.dumps(session["history"], ensure_ascii=False))


def system_message(session):
    document = yaml_document(session["tree"])
    if len(document) > 40000:
        outline = []
        pending = [(session["tree"], None)]
        while pending:
            node, parent = pending.pop()
            outline.append({"id": node["id"], "name": node["name"], "parent": parent})
            for child in reversed(node["children"]):
                pending.append((child, node["id"]))
        document = "文档较大，以下仅为大纲，修改前用 read_node 读取详情：\n" + json.dumps(outline, ensure_ascii=False)
    return {"role": "system", "content": (
        SYSTEM + f"\n当前文档修订 {session['revision']}：\n" + document
        + "\n较早会话的摘要（可能不完整，以当前文档与用户新指令为准）：\n" + session["summary"]
    )}


async def completion(profile, model, messages, turn, save, *, thinking=False, effort="low", tools=False):
    provider = model["provider"]
    actual = profile["model"].lower().split("/")[-1]
    if actual.startswith("qwen"):
        provider = "qwen"
    elif actual.startswith("deepseek"):
        provider = "deepseek"
    wire_messages = []
    for message in messages:
        wire = dict(message)
        if wire["role"] == "assistant":
            if provider == "deepseek":
                wire.setdefault("reasoning_content", "")
            else:
                wire.pop("reasoning_content", None)
        wire_messages.append(wire)
    request = {
        "model": profile["model"], "messages": wire_messages,
        "stream": True, "stream_options": {"include_usage": True},
        "max_tokens": 393216 if provider == "deepseek" else 131072,
    }
    if provider == "deepseek":
        request["thinking"] = {"type": "enabled" if thinking else "disabled"}
        if thinking:
            request["reasoning_effort"] = effort
    else:
        request["enable_thinking"] = thinking
    if tools:
        request["tools"] = tool_definitions()
        request["tool_choice"] = "auto"
    content = ""
    reasoning = ""
    calls = {}
    finish = None
    saved_at = time.monotonic()
    answer_start = turn["answer"]
    reason_start = turn["reasoning"]
    async for packet in stream_model(profile["base_url"], profile["api_key"], request, 600):
        if packet.get("error"):
            raise ValueError("模型服务错误：" + json.dumps(packet["error"], ensure_ascii=False))
        if packet.get("usage"):
            turn["usage"].append(packet["usage"])
        for choice in packet.get("choices", []):
            if choice.get("index", 0) != 0:
                continue
            delta = choice.get("delta") or choice.get("message") or {}
            content += response_text(delta.get("content"))
            reasoning += response_text(delta.get("reasoning_content"))
            for ordinal, item in enumerate(delta.get("tool_calls", [])):
                index = item.get("index", ordinal)
                call = calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                call["id"] += item.get("id", "")
                function = item.get("function") or {}
                call["function"]["name"] += function.get("name", "")
                call["function"]["arguments"] += function.get("arguments", "")
            finish = choice.get("finish_reason") or finish
        turn["answer"] = answer_start + content
        turn["reasoning"] = reason_start + reasoning
        if time.monotonic() - saved_at > 0.6:
            save()
            saved_at = time.monotonic()
    if finish == "length":
        raise ValueError("模型服务截断了回复，未执行本轮不完整的工具调用；请缩小本次修改范围后重试")
    if finish not in {"stop", "tool_calls"}:
        raise ValueError(f"模型未正常结束回复：{finish or '未返回完成原因'}")
    message = {"role": "assistant", "content": content, "reasoning_content": reasoning}
    if calls:
        message["tool_calls"] = []
        for index in sorted(calls):
            call = calls[index]
            call["id"] = call["id"] or "call_" + uuid4().hex
            message["tool_calls"].append(call)
    elif not content.strip():
        raise ValueError("模型没有返回正文或工具调用")
    save()
    return message


async def compact(session, profile, model, save, now):
    history = session["history"]
    if not history:
        return
    starts = [index for index, message in enumerate(history) if message["role"] == "user"]
    split = starts[-1] if len(starts) >= 2 else len(history)
    old = history[:split]
    if not old:
        return
    session["phase"] = "正在压缩较早会话"
    save()
    record = {"id": uuid4().hex, "created_at": now(), "answer": "", "reasoning": "", "usage": [], "status": "RUNNING", "before_chars": context_chars(session)}
    session["compactions"].append(record)
    prompt = (
        "请压缩需求分析对话，只返回中文摘要。保留：用户目标、已确认业务规则、明确不做的内容、"
        "关键术语、未决问题、被否定的方案及原因、当前任务。不要新增假设或重写需求树。"
        "当前文档会另外完整提供给后续助手；不必重复所有文档或工具参数。尽量控制在1200汉字内，重要规则优先。\n"
        "已有摘要：\n" + session["summary"] + "\n待压缩会话：\n" + json.dumps(old, ensure_ascii=False)
    )
    try:
        message = await completion(profile, model, [{"role": "user", "content": prompt}], record, save)
        session["summary"] = message["content"]
        session["history"] = history[split:]
        record.update(status="COMPLETED", after_chars=context_chars(session))
    except BaseException:
        record["status"] = "INTERRUPTED"
        raise
    finally:
        save()
