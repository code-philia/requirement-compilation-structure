"""Native scoped file implementation with real initialization feedback."""

from copy import deepcopy

from infrastructure.shared.agent import AgentTool, BaseAgent, AgentLoopExhausted
from infrastructure.shared.agent.feedback import compact_feedback
from infrastructure.shared.agent.tools import FileToolError
from infrastructure.shared.models.streaming import IncompleteModelStreamError
from infrastructure.utils.presentation.console import DemoConsole


class DatabaseFileAgent(BaseAgent):
    def __init__(self, instructions, files, gate, *, feedback_filter=None, **options):
        super().__init__(**options)
        self.instructions, self.files, self.gate = instructions, files, gate
        self.feedback_filter = feedback_filter or compact_feedback
        self.accepted = None
        self.last_feedback = None

    def build_system_prompt(self):
        return self.instructions + """
Use the advertised NATIVE function tools; do not serialize tool calls in response text.
Implement promptly from supplied files, schema and evidence. Batch independent reads;
do not reread unchanged supplied files or search without a named missing dependency.
Use edit_file for all persistent writes; file scope is enforced by the existing tools.
Use local exact-span replacements in shared files and preserve unrelated behavior.
When implementation is ready call finish_implementation. Its real result decides whether
this task is complete. On failure repair the reported cause and call it again. Do not
claim completion in text, suppress an initialization failure or weaken expected behavior.
"""

    def build_user_prompt(self, input):
        return {"task": input, "scope": self.files.scope_state(), "files": self.files.state()}

    def build_tools(self):
        tools = []
        for schema in self.files.schemas():
            name = schema["tool"]
            if name not in {"read_file", "list_files", "search_files", "edit_file", "bash"}:
                continue
            parameters = deepcopy(schema["parameters"])
            parameters["properties"].pop("tool", None)
            parameters["required"] = [key for key in parameters["required"] if key != "tool"]

            def execute(_name=name, **arguments):
                if _name == "edit_file":
                    self.accepted = None
                try:
                    return self.files.execute([{"tool": _name, **arguments}])
                except FileToolError as error:
                    return {"status": "NEEDS_REPAIR", "feedback": error.feedback}

            # Native protocol wording must not teach the old JSON tool envelope.
            description = schema["description"].replace("in diagnosis.reason", "briefly in your explanation").replace(
                "using separate read_file entries in one tool_calls array (at most eight context calls total)",
                "using several native read_file calls in the same response")
            tools.append(AgentTool(name, description, parameters, execute))
        tools.append(AgentTool("finish_implementation", "Run the task's real publication/initialization checks and receive repair feedback.",
            {"type": "object", "properties": {}, "additionalProperties": False}, self.finish))
        return tools

    def finish(self):
        try:
            result = self.gate()
        except (ValueError, RuntimeError) as error:
            feedback = self.feedback_filter(getattr(error, "feedback", {"error": str(error)}))
            self.last_feedback = feedback
            self.accepted = None
            return {"status": "NEEDS_REPAIR", "feedback": feedback,
                "scope": self.files.scope_state(), "files": self.files.state()}
        self.accepted = result
        return {"status": "GREEN", "checks": result}

    def run(self, input, max_turns=10, feedback=None, console=None, label="Database implementation"):
        self.accepted = None
        self.start(input)
        if feedback is not None:
            self.messages.append({"role": "user", "content": self._feedback_text(feedback)})
        console = console or DemoConsole(False)
        for turn in range(1, max_turns + 1):
            console.show(f"{label} | Native agent {turn}/{max_turns}", "Implement, then call finish_implementation; repair only concrete failures.")
            try:
                message = self.step(tool_choice="required")
            except (ValueError, IncompleteModelStreamError) as error:
                self.messages.append({"role": "user", "content": str(error) + " Return a smaller complete native tool batch."})
                continue
            self.execute_tools(message)
            if self.accepted is not None:
                return {"status": "GREEN", "turns": turn, "checks": self.accepted}
        error = AgentLoopExhausted(f"{label} exhausted {max_turns} turns; files remain available for repair")
        error.turns = max_turns
        error.feedback = self.last_feedback
        raise error

    def _feedback_text(self, feedback):
        import json
        return json.dumps({"repair_feedback": self.feedback_filter(feedback),
            "scope": self.files.scope_state(), "files": self.files.state()}, ensure_ascii=False)


def run_database_agent(model, instructions, task, files, gate, max_turns, console, label,
        feedback=None, feedback_filter=None):
    """Keep stage ownership while adapting existing scoped file tools to native calls."""
    return DatabaseFileAgent(instructions, files, gate, model=model,
        feedback_filter=feedback_filter).run(task, max_turns=max_turns,
            feedback=feedback, console=console, label=label)
