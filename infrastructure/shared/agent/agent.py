"""Stage-owned prompts and workflows with native function tool calling."""

from dataclasses import dataclass
import inspect
import json
from typing import Any, Callable

from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.agent import AgentLogger
from infrastructure.utils.presentation.model_io import record_tool_execution


@dataclass(frozen=True)
class AgentTool:
    """An explicit native function schema and its stage-owned implementation.

    Register only authorized operations. This abstraction grants no filesystem,
    shell or network access; handlers retain their existing scope enforcement.
    """

    name: str
    description: str
    parameters: dict
    handler: Callable[..., Any]

    def definition(self) -> dict:
        return {"type": "function", "function": {"name": self.name,
            "description": self.description, "parameters": self.parameters}}


class AgentLoopExhausted(RuntimeError):
    """A bounded loop ended without a final answer; conversation stays on the agent."""


class BaseAgent:
    """Common identity, prompts, native calls and optional tool loop.

    Stages override run for a fixed workflow or call run_loop for iterative work.
    Acceptance, retries, checkpoints and business decisions belong to that stage.
    Use a separate instance per task; conversation state is not concurrency-safe.
    """

    def __init__(self, model_name: str | None = None, *, model=None,
            json_mode: bool = False) -> None:
        self.model = model if model is not None else TextModel(
            model_name=model_name, json_mode=json_mode)
        self.logger = AgentLogger(type(self).__name__)
        self.model.logger = self.logger
        self.messages: list[dict] = []
        self.tools: dict[str, AgentTool] = {}

    def build_system_prompt(self) -> str:
        return ""

    def build_user_prompt(self, input: dict) -> str | dict | list:
        return input

    def build_tools(self) -> list[AgentTool]:
        """Declare task-scoped native tools; no capabilities are enabled implicitly."""
        return []

    def start(self, input: dict) -> list[dict]:
        """Begin a fresh task; a custom run can then call step/execute_tools itself."""
        tools = self.build_tools()
        tools = [tool for tool in tools if tool.name != "bash"]
        self.tools = {tool.name: tool for tool in tools}
        if len(self.tools) != len(tools):
            raise ValueError("Agent tool names must be unique")
        prompt = self.build_user_prompt(input)
        if isinstance(prompt, dict):
            prompt = json.dumps(prompt, ensure_ascii=False)
        self.messages = [{"role": "system", "content": self.build_system_prompt()},
            {"role": "user", "content": prompt}]
        return self.messages

    def step(self, *, tool_choice: str | dict = "auto"):
        """Request one native response and retain its IDs and reasoning metadata."""
        if not self.messages:
            raise RuntimeError("Call start(input) before step()")
        definitions = [tool.definition() for tool in self.tools.values()]
        message = self.model.chat(self.messages, tools=definitions, tool_choice=tool_choice)
        record = message.model_dump(mode="json", exclude_none=True)
        self.messages.append(record)
        return message

    def execute_tools(self, message) -> list[dict]:
        """Execute native calls in order, returning every result under its call ID.

        Multiple calls in one response are supported. Execution stays sequential so
        dependent writes preserve order. Ordinary handler/argument errors become tool
        feedback for the next model turn; process interrupts are never swallowed.
        Successful operations are retained, so stages own any rollback semantics.
        """
        results = []
        for call in message.tool_calls or []:
            try:
                if call.type != "function":
                    raise ValueError("Only native function tools are supported")
                name = call.function.name
                if name not in self.tools:
                    raise ValueError(f"Unknown tool: {name}")
                arguments = json.loads(call.function.arguments)
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be a JSON object")
                handler = self.tools[name].handler
                inspect.signature(handler).bind(**arguments)
                value = handler(**arguments)
                result = {"ok": True, "result": value}
            except Exception as error:
                result = {"ok": False, "error": {
                    "type": type(error).__name__, "message": str(error)}}
            record = {"role": "tool", "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False, default=str)}
            self.messages.append(record)
            results.append(record)
            record_tool_execution(call.model_dump(mode="json"),
                json.loads(record["content"]), logger=self.logger)
        return results

    def run_loop(self, input: dict, *, max_turns: int = 20,
            tool_choice: str | dict = "auto"):
        """Opt-in loop; returns the final SDK message, not an acceptance verdict.

        Stages needing submit/finish tools or required calls should override run
        and own completion instead of using this text-final-answer convention.
        """
        if max_turns < 1:
            raise ValueError("max_turns must be positive")
        self.start(input)
        for _ in range(max_turns):
            message = self.step(tool_choice=tool_choice)
            if not message.tool_calls:
                return message
            self.execute_tools(message)
        raise AgentLoopExhausted(
            f"{type(self).__name__} exhausted {max_turns} model turns; "
            "task completion has not been established")

    def run(self, input: dict):
        """Implement a fixed workflow or delegate to run_loop in each stage."""
        raise NotImplementedError("Stage agents must implement run(input)")
