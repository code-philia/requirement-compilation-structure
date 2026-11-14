"""Readable agent conversation and tool execution logs."""

import json
import hashlib

from infrastructure.utils.presentation.logging import full_detail


class AgentLogger:
    def __init__(self, name: str) -> None:
        self.name = name
        self.last_call_id: str | None = None
        self._logged_messages: list[str] = []

    def format_message(self, message: dict) -> str:
        parts = []
        content = message.get("content")
        if isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    parts.append(item["text"])
                elif item.get("type") == "image_url":
                    parts.append("[图片输入]")
        elif isinstance(content, str) and content:
            try:
                content = json.dumps(json.loads(content), ensure_ascii=False, indent=2)
            except ValueError:
                pass
            parts.append(content)
        if message.get("refusal"):
            parts.append("模型拒绝：" + message["refusal"])
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            arguments = function.get("arguments", "")
            try:
                arguments = json.dumps(json.loads(arguments), ensure_ascii=False, indent=2)
            except (ValueError, TypeError):
                arguments = str(arguments)
            parts.append(f"调用工具：{function.get('name', '(unknown)')}\n"
                f"调用 ID：{call.get('id', '(unknown)')}\n参数：\n{arguments}")
        return "\n\n".join(parts) or "（无正文或工具调用）"

    def format_input(self, arguments: dict) -> str:
        tool_names = []
        for tool in arguments.get("tools") or []:
            tool_names.append(tool.get("function", {}).get("name", "(unknown)"))
        parts = [f"智能体：{self.name}\n本轮模型输入\n模型：{arguments.get('model', '')}\n"
            "可用工具：" + (", ".join(tool_names) or "无")]
        calls = {}
        first_user = True
        for index, message in enumerate(arguments.get("messages", []), 1):
            role = message.get("role")
            if role in {"system", "developer"}:
                title = "系统提示词"
            elif role == "user":
                title = "用户提示词" if first_user else "补充输入 / 修正反馈"
                first_user = False
            elif role == "assistant":
                title = "历史模型输出"
            elif role == "tool":
                call_id = message.get("tool_call_id", "")
                title = f"历史工具执行结果：{calls.get(call_id, '(unknown)')}（{call_id}）"
            else:
                title = str(role)
            for call in message.get("tool_calls") or []:
                calls[call.get("id", "")] = call.get("function", {}).get("name", "(unknown)")
            parts.append(f"消息 {index} · {title}\n" + self.format_message(message))
        return "\n\n".join(parts)

    def format_output(self, response: dict) -> str:
        parts = [f"智能体：{self.name}\n本轮模型输出"]
        for index, choice in enumerate(response.get("choices", []), 1):
            parts.append(f"回复 {index}（结束原因：{choice.get('finish_reason', '')}）\n" +
                self.format_message(choice.get("message", {})))
        return "\n\n".join(parts)

    def log_input(self, label: str, arguments: dict) -> dict:
        """Human logs show new context only; the transport audit keeps full requests."""
        messages = arguments.get('messages',[])
        fingerprints = [hashlib.sha256(json.dumps(message,sort_keys=True,ensure_ascii=False,
            default=str).encode()).hexdigest() for message in messages]
        prefix = 0
        for previous,current in zip(self._logged_messages,fingerprints):
            if previous!=current:
                break
            prefix += 1
        self._logged_messages = fingerprints
        visible = {**arguments,'messages':messages[prefix:],'_history_omitted':prefix,'_total_messages':len(messages)}
        note = f'已省略 {prefix} 条已记录历史；本轮新增 {len(messages)-prefix} 条消息。\n'
        full_detail(f"[MODEL INPUT] {label}", note + (self.format_input(visible)
            if visible['messages'] else '没有新增上下文；重试同一请求，不重复展示旧对话。'))
        return visible

    def log_tool_execution(self, tool_call: dict, result: dict) -> None:
        text = self.format_message({"tool_calls": [tool_call]})
        text += "\n\n执行结果：\n" + json.dumps(result, ensure_ascii=False, indent=2)
        full_detail(f"[TOOL EXECUTION] {self.name}", text)
