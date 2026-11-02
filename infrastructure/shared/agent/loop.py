"""Bounded file editing with failure attribution and real acceptance checks."""

import json

from infrastructure.shared.agent.discovery import project_index, DISCOVERY_RULES, DiscoverySession
from infrastructure.shared.agent.conventions import task_conventions

from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.tools.protocol import FILE_TOOL_RULES
from infrastructure.shared.agent.proposals import RESPONSE_ERRORS, response_feedback
from infrastructure.shared.project.git import checkpoint


class AgentExhausted(ValueError):
    """A recoverable task failure with the last real repair feedback."""

    def __init__(self, label, turns, feedback):
        super().__init__(f"Agent exhausted {turns} rounds for {label}")
        self.turns = turns
        self.feedback = feedback


def run_file_agent(model, instructions: str, task: dict, files: FileTools, gate,
        max_turns: int, console, label: str, feedback=None, feedback_filter=None, context_index=None) -> dict:
    """Refresh files and paths; optionally select failure-related files before repair.

    The stage-owned feedback filter may add writable sources/read-only references
    and condense check reports. It cannot change the acceptance gate or its result.
    """
    if max_turns < 1:
        raise ValueError("--max-turns must be positive")
    index = context_index if context_index is not None else project_index(files.output)
    discovery, context_result = DiscoverySession(index), None
    feedback = [] if feedback is None else [feedback_filter(feedback) if feedback_filter else feedback]
    for turn in range(1, max_turns + 1):
        console.show(f"{label} | Edit round {turn}/{max_turns}",
            "Generate file edits, then run the stage's compilation and test acceptance checks.")
        response, applied = None, False
        try:
            def request_model():
                request = {"task": files.task_state(task), "files": files.state(), "feedback": feedback,
                    "context_kinds": list(index.records()), "tools": files.schemas()}
                conventions = task_conventions(files.output, task)
                if conventions:
                    request["task"]["shared_conventions"] = conventions
                if context_result is not None:
                    request["context_result"] = context_result
                return model.generate_json(instructions + "\n\n" + FILE_TOOL_RULES + "\n\n" + DISCOVERY_RULES, request)
            response = request_model()
            while isinstance(response, dict):
                if "context_request" in response:
                    query = response["context_request"]
                    console.show(label + " | Context query", json.dumps(query, ensure_ascii=False))
                    if isinstance(query, dict) and query.get("kind") == "file" and "ids" in query:
                        context_result = discovery.observe({"error": "Use read_file for file content; context_request discovers semantic records or file candidates."})
                    else:
                        context_result = discovery.resolve(query)
                elif "tool_calls" in response and files.effect(response["tool_calls"]) == "read":
                    calls = response["tool_calls"]
                    console.show(label + " | Read files", str([call.get("arguments", {}).get("path") for call in calls]))
                    try:
                        context_result = {"tool_results": files.execute(calls)}
                    except (*RESPONSE_ERRORS, OSError) as error:
                        context_result = {"tool_results": [{"error": getattr(error, "feedback", {"message": str(error)})}]}
                    context_result = discovery.observe(context_result)
                else:
                    break
                response = request_model()
            if isinstance(response, dict) and response.get("diagnosis"):
                console.show(label + " | Failure diagnosis", json.dumps(response["diagnosis"], ensure_ascii=False, indent=2))
            calls = response["tool_calls"]
            results = files.execute(calls)
            context_result = {"tool_results": results}
            changes = [change for change in files.last_changes if "/tests/" in change["path"]
                and change["before"] is not None and change["before"] != change["after"]]
            if changes:
                audit = files.output / ".arc/test_repairs.jsonl"
                audit.parent.mkdir(parents=True, exist_ok=True)
                with audit.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"task": label, "turn": turn, "diagnosis": response.get("diagnosis"),
                        "feedback": feedback, "changes": changes}, ensure_ascii=False) + "\n")
            applied = True
            if files.pending_target:
                raise ValueError("Create task.file_target with edit_file before running acceptance checks")
            console.show(f"{label} | Edit round {turn}/{max_turns}",
                str([change["path"] for change in files.last_changes]))
            checkpoint(files.output, task=label, action=f"Apply file edits in round {turn}", status="PROPOSED",
                details={"round": turn, "files": [change["path"] for change in files.last_changes],
                    "diagnosis": response.get("diagnosis")})
            checks = gate()
            checkpoint(files.output, task=label, action=f"Accept edit round {turn}",
                details={"round": turn, "checks": checks})
            return {"turns": turn, "checks": checks}
        except (*RESPONSE_ERRORS, RuntimeError, OSError) as error:
            message = str(error)
            console.show(f"{label} | Repair feedback", message)
            rejected = (getattr(error, "feedback", {"error": message}) if applied
                else response_feedback(error, response))
            if isinstance(response, dict) and response.get("diagnosis") and isinstance(rejected, dict):
                rejected = {**rejected, "previous_diagnosis": response["diagnosis"]}
            feedback = [feedback_filter(rejected) if feedback_filter else rejected]
            checkpoint(files.output, task=label, action=f"Reject edit round {turn}", status="REJECTED",
                details={"round": turn, "applied": applied, "feedback": feedback})
    raise AgentExhausted(label, max_turns, feedback)
