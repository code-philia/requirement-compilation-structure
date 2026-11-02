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
        max_turns: int, console, label: str, feedback=None, feedback_filter=None, context_index=None,
        allow_discovery=True) -> dict:
    """Refresh files and paths; optionally select failure-related files before repair.

    The stage-owned feedback filter may add writable sources/read-only references
    and condense check reports. It cannot change the acceptance gate or its result.
    """
    if max_turns < 1:
        raise ValueError("--max-turns must be positive")
    index = None
    if allow_discovery:
        index = context_index if context_index is not None else project_index(files.output)
    discovery, context_result = DiscoverySession(index), None
    read_files = {}
    feedback = [] if feedback is None else [feedback_filter(feedback) if feedback_filter else feedback]
    for turn in range(1, max_turns + 1):
        console.show(f"{label} | Edit round {turn}/{max_turns}",
            "Generate file edits, then run the stage's compilation and test acceptance checks.")
        response, applied = None, False
        try:
            def request_model():
                request = {"task": files.task_state(task), "files": files.state(), "feedback": feedback,
                    "context_kinds": list(index.records()) if index is not None else [], "tools": files.schemas()}
                if read_files:
                    request["read_files"] = read_files
                if discovery.evidence:
                    request["context_records"] = discovery.evidence
                conventions = task_conventions(files.output, task)
                if conventions:
                    request["task"]["shared_conventions"] = conventions
                if context_result is not None:
                    request["context_result"] = context_result
                rules = instructions + "\n\n" + FILE_TOOL_RULES
                if allow_discovery:
                    rules += "\n\n" + DISCOVERY_RULES
                else:
                    rules += "\nSemantic discovery is disabled for this task. Use supplied evidence and read_file only."
                return model.generate_json(rules, request)
            response = request_model()
            while isinstance(response, dict):
                if "context_request" in response:
                    if not allow_discovery:
                        raise ValueError("Semantic discovery is disabled for this task; use supplied requirements and read_file for allowed database files")
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
                        results = files.execute(calls)
                        observation = {"tool_results": results}
                        for item in results:
                            record = item["result"]
                            excerpts = read_files.setdefault(record["path"], [])
                            # Keep distinct ranges; a wider read replaces excerpts it covers.
                            excerpts[:] = [old for old in excerpts if not (
                                record["start_line"] <= old["start_line"] and record["end_line"] >= old["end_line"])]
                            excerpts.append(record)
                        context_result = {"read_paths": [item["result"]["path"] for item in results]}
                    except (*RESPONSE_ERRORS, OSError) as error:
                        context_result = {"tool_results": [{"error": getattr(error, "feedback", {"message": str(error)})}]}
                        observation = context_result
                    observed = discovery.observe(observation)
                    if observed.get("next_action"):
                        context_result["next_action"] = observed["next_action"]
                else:
                    break
                response = request_model()
            if isinstance(response, dict) and response.get("diagnosis"):
                console.show(label + " | Failure diagnosis", json.dumps(response["diagnosis"], ensure_ascii=False, indent=2))
            calls = response["tool_calls"]
            results = files.execute(calls)
            for change in files.last_changes:
                read_files.pop(change["path"], None)
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
