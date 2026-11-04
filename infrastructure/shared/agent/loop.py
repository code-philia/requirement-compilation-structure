"""Bounded file editing with failure attribution and real acceptance checks."""

import json

from infrastructure.shared.agent.conventions import task_conventions
from infrastructure.shared.agent.feedback import compact_feedback

from infrastructure.shared.agent.tools import FileTools, FileToolError
from infrastructure.shared.agent.tools.protocol import FILE_TOOL_RULES
from infrastructure.shared.agent.proposals import RESPONSE_ERRORS, response_feedback
from infrastructure.shared.project.git import checkpoint
from infrastructure.utils.files import read_source


class AgentExhausted(ValueError):
    """A recoverable task failure with the last real repair feedback."""

    def __init__(self, label, turns, feedback):
        super().__init__(f"Agent exhausted {turns} rounds for {label}")
        self.turns = turns
        self.feedback = feedback


def run_file_agent(model, instructions: str, task: dict, files: FileTools, gate,
        max_turns: int, console, label: str, feedback=None, feedback_filter=None) -> dict:
    """Refresh files and paths; optionally select failure-related files before repair.

    The stage-owned feedback filter may add writable sources/read-only references
    and condense check reports. It cannot change the acceptance gate or its result.
    """
    if max_turns < 1:
        raise ValueError("--max-turns must be positive")
    if feedback_filter is None:
        feedback_filter = compact_feedback
    context_result = None
    read_observations = {}
    files.read_files = {}
    read_files = files.read_files
    initial = feedback_filter(feedback) if feedback is not None and feedback_filter else feedback
    last_acceptance = {"origin": "initial_observation" if initial is not None else "not_run",
        "round": None, "stale": False, "checks": initial}
    feedback = []
    for turn in range(1, max_turns + 1):
        console.show(f"{label} | Edit round {turn}/{max_turns}",
            "Generate file edits, then run the stage's compilation and test acceptance checks.")
        response, applied, checking = None, False, False
        try:
            def request_model():
                # Gates may regenerate wiring outside edit_file; discard stale excerpts too.
                for path, excerpts in list(read_files.items()):
                    target = files.path(path)
                    if not target.is_file():
                        read_files.pop(path)
                        continue
                    lines = read_source(target).splitlines(keepends=True)
                    for excerpt in excerpts:
                        content = "".join(lines[excerpt["start_line"] - 1:excerpt["end_line"]])
                        if len(lines) != excerpt["total_lines"] or content != excerpt["content"]:
                            read_files.pop(path)
                            break
                request = {"task": task, "scope": files.scope_state(), "files": files.state(), "feedback": feedback,
                    "tools": files.schemas(),
                    "round_state": {"round": turn, "acceptance_ran": False},
                    "last_acceptance": last_acceptance}
                if read_files:
                    request["read_files"] = read_files
                conventions = task_conventions(files.output, task)
                if conventions:
                    request["task"]["shared_conventions"] = conventions
                if context_result is not None:
                    request["context_result"] = context_result
                rules = instructions + "\n\n" + FILE_TOOL_RULES
                rules += "\nImplementation uses the supplied requirement, design, scope and related files. Semantic queries are not available."
                return model.generate_json(rules, request)
            response = request_model()
            while isinstance(response, dict):
                if "context_request" in response:
                    raise FileToolError("QUERY_DISABLED", "Implementation tasks do not query designs. Use the supplied requirement/design and read_file within scope.")
                elif "tool_calls" in response and files.effect(response["tool_calls"]) == "read":
                    calls = response["tool_calls"]
                    console.show(label + " | Read files", str([call.get("path") for call in calls]))
                    results = files.execute(calls)
                    observation = {"tool_results": results}
                    for item in results:
                        if "error" in item:
                            continue
                        record = item["result"]
                        if record.get("cached"):
                            continue
                        excerpts = read_files.setdefault(record["path"], [])
                        # Keep distinct ranges; a wider read replaces excerpts it covers.
                        excerpts[:] = [old for old in excerpts if not (
                            record["start_line"] <= old["start_line"] and record["end_line"] >= old["end_line"])]
                        excerpts.append(record)
                    context_result = {
                        "phase": "context_read", "acceptance_ran": False,
                        "read_paths": [item["result"]["path"] for item in results if "result" in item],
                        "errors": [item["error"] for item in results if "error" in item],
                        "references": [item["result"] for item in results if item.get("result", {}).get("cached")],
                    }
                    if context_result["errors"]:
                        console.show(label + " | Read feedback (checks not run)", json.dumps(context_result["errors"], ensure_ascii=False))
                    fingerprint = json.dumps(observation, sort_keys=True, ensure_ascii=False)
                    count = read_observations.get(fingerprint, 0) + 1
                    read_observations[fingerprint] = count
                    if count >= 3:
                        raise FileToolError("REPEATED_READ", "The same read results were supplied repeatedly. Use the retained files or edit the implementation.")
                    if count == 2:
                        context_result["next_action"] = "These read results are already retained. Use them instead of reading again."
                else:
                    break
                response = request_model()
            if isinstance(response, dict) and response.get("diagnosis"):
                console.show(label + " | Failure diagnosis", json.dumps(response["diagnosis"], ensure_ascii=False, indent=2))
            calls = response["tool_calls"]
            results = files.execute(calls)
            for change in files.last_changes:
                read_files.pop(change["path"], None)
                if change["before"] != change["after"]:
                    last_acceptance["stale"] = True
            context_result = {"tool_results": results}
            changes = [change for change in files.last_changes if "/tests/" in change["path"]
                and change["before"] is not None and change["before"] != change["after"]]
            if changes:
                audit = files.output / ".arc/test_repairs.jsonl"
                audit.parent.mkdir(parents=True, exist_ok=True)
                with audit.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"task": label, "turn": turn, "diagnosis": response.get("diagnosis"),
                        "feedback": feedback, "last_acceptance": last_acceptance, "changes": changes}, ensure_ascii=False) + "\n")
            applied = True
            console.show(f"{label} | Edit round {turn}/{max_turns}",
                str([change["path"] for change in files.last_changes]))
            checkpoint(files.output, task=label, action=f"Apply file edits in round {turn}", status="PROPOSED",
                details={"round": turn, "files": [change["path"] for change in files.last_changes],
                    "diagnosis": response.get("diagnosis")})
            checking = True
            checks = gate()
            checkpoint(files.output, task=label, action=f"Accept edit round {turn}",
                details={"round": turn, "checks": checks})
            return {"turns": turn, "checks": checks, "files": sorted(files.changed_paths)}
        except (*RESPONSE_ERRORS, RuntimeError, OSError) as error:
            message = str(error)
            phase = "acceptance" if checking else "tool_protocol"
            title = "Acceptance failed" if checking else "Tool feedback (checks not run)"
            console.show(f"{label} | {title}", message)
            if isinstance(error, FileToolError):
                rejected = {"error": message, "details": error.feedback}
            elif checking:
                rejected = getattr(error, "feedback", {"error": message})
            else:
                rejected = response_feedback(error, response)
            if isinstance(response, dict) and response.get("diagnosis") and isinstance(rejected, dict):
                rejected = {**rejected, "previous_diagnosis": response["diagnosis"]}
            rejected = feedback_filter(rejected) if feedback_filter else rejected
            if checking:
                last_acceptance = {"origin": "agent_gate", "round": turn, "stale": False, "checks": rejected}
            feedback = [{"phase": phase, "round": turn, "acceptance_ran": checking,
                "error": message, "details": rejected,
                "next_action": "Repair the code or evidenced test issue using these fresh check results." if checking
                    else "Resolve this tool/path/target error first. No new compilation or tests ran in this round; do not infer a new business failure from stale checks."}]
            checkpoint(files.output, task=label, action=f"Reject edit round {turn}", status="REJECTED",
                details={"round": turn, "applied": applied, "phase": phase,
                    "acceptance_ran": checking, "last_acceptance_stale": last_acceptance["stale"], "feedback": feedback})
    raise AgentExhausted(label, max_turns, feedback)
