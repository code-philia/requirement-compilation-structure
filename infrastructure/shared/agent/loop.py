"""Bounded file editing with failure attribution and real acceptance checks."""

import json
import re

from infrastructure.shared.models.text import ModelProtocolError

from infrastructure.shared.agent.conventions import task_conventions
from infrastructure.shared.agent.testing_reference import testing_reference
from infrastructure.shared.agent.context import implementation_context
from infrastructure.shared.agent.feedback import compact_feedback, failure_signature, TestSetupRequired
from infrastructure.shared.agent.repairs import UpstreamRepairRequired

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


class ProtocolExhausted(AgentExhausted):
    """A bounded response-format retry failed before implementation checks ran."""


class RepairStalled(AgentExhausted):
    """Repeated actual failures need diagnosis instead of the same implementation loop."""


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
    test_reference = testing_reference(task)
    read_observations = {}
    files.read_files = {}
    read_files = files.read_files
    initial = feedback_filter(feedback) if feedback is not None and feedback_filter else feedback
    last_acceptance = {"origin": "initial_observation" if initial is not None else "not_run",
        "round": None, "stale": False, "checks": initial}
    feedback = []
    context_batches = 0
    last_failure, same_failure = None, 0
    last_tool_failure, same_tool_failure = None, 0
    protocol_retries = 0
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
                if files.stage in {'backend', 'frontend', 'ui'}:
                    failure_text = json.dumps(feedback or initial or {}, ensure_ascii=False)
                    files.focus_paths = set(re.findall(r'(?:frontend|backend)/[\w./-]+\.(?:tsx?|jsx?|sql)', failure_text))
                    # Retain bounded, recent excerpts; dropped excerpts can be requested again.
                    remaining = 32000
                    for path in reversed(list(read_files)):
                        kept = []
                        for excerpt in reversed(read_files[path]):
                            size = len(excerpt['content'])
                            if size <= remaining:
                                kept.insert(0, excerpt)
                                remaining -= size
                        if kept:
                            read_files[path] = kept
                        else:
                            del read_files[path]
                request = {"task": task, "scope": files.scope_state(), "files": files.state(), "feedback": feedback,
                    "tools": [schema for schema in files.schemas() if (context_batches < 4 and files.discovery_no_progress < 3)
                        or schema.get('tool') not in {'list_files', 'search_files', 'bash'}],
                    "round_state": {"round": turn, "acceptance_ran": False,
                        "context_batches_remaining": max(0, 8-context_batches),
                        "broad_discovery_batches_remaining": max(0, 4-context_batches),
                        "next_action": "Implement now if evidence is sufficient; do not spend the remaining budget by default."},
                    "last_acceptance": last_acceptance}
                if test_reference:
                    request['test_tool_reference'] = test_reference
                if files.discovery_cache:
                    request['discovery_cache'] = files.discovery_cache
                if files.discovery_no_progress >= 3:
                    request['round_state']['next_action'] = (
                        'Repeated discovery produced no new evidence. Implement from retained content '
                        'or use a precise read_file for a named missing span; broad discovery is temporarily hidden.')
                if files.stage in {"backend", "frontend", "ui"} and files.writable is None:
                    request["implementation_context"] = implementation_context(files)
                # A fully supplied file must not also occupy retained read context.
                for path in list(read_files):
                    if path in files.supplied_contents:
                        read_files.pop(path)
                if read_files:
                    request["read_files"] = read_files
                conventions = task_conventions(files.output, task)
                if conventions:
                    request["task"]["shared_conventions"] = conventions
                if context_result is not None:
                    request["context_result"] = context_result
                rules = instructions + "\n\n" + FILE_TOOL_RULES
                rules += "\nImplementation uses the supplied requirement, design, scope and related files. Semantic queries are not available."
                nonlocal protocol_retries
                for protocol_attempt in range(3):
                    try:
                        proposal = model.generate_json(rules, request)
                        if isinstance(proposal, list) and proposal and all(
                                isinstance(call, dict) and call.get('tool') in files.tool_registry for call in proposal):
                            proposal = {'tool_calls': proposal}
                        if not isinstance(proposal, dict) or not isinstance(proposal.get('tool_calls'), list):
                            if not isinstance(proposal, dict) or 'context_request' not in proposal:
                                raise ModelProtocolError('Return one object containing a tool_calls array')
                        return proposal
                    except (json.JSONDecodeError, ModelProtocolError) as error:
                        protocol_retries += 1
                        console.show(label + ' | Response protocol retry',
                            f'{protocol_attempt + 1}/3: {str(error)[:200]}. No source edits or acceptance ran.')
                        checkpoint(files.output, task=label, action='Retry malformed model response',
                            status='REJECTED', details={'error': str(error)[:500], 'attempt': protocol_attempt + 1,
                                'implementation_round': turn, 'acceptance_ran': False})
                        if protocol_attempt == 2:
                            raise ProtocolExhausted(label + ' / response protocol', turn,
                                {'phase': 'model_protocol', 'error': str(error)[:1000]}) from error
                        request['protocol_correction'] = (
                            'Previous output was empty or invalid JSON. Return a single JSON object '
                            'with tool_calls. Keep the edit batch small; no fences, prose or whitespace-only response.')
            response = request_model()
            while isinstance(response, dict):
                if "context_request" in response:
                    raise FileToolError("QUERY_DISABLED", "Implementation tasks do not query designs. Use the supplied requirement/design and read_file within scope.")
                elif "tool_calls" in response and files.effect(response["tool_calls"]) == "read":
                    calls = response["tool_calls"]
                    precise = all(call.get('tool') == 'read_file' for call in calls if isinstance(call, dict))
                    if context_batches >= 8 or context_batches >= 4 and not precise:
                        # Avoid turning a local discovery limit into an input/schema
                        # revision. Observe actual executable gaps, then repair code.
                        console.show(label + ' | Discovery budget reached',
                            'Retained evidence is available. Checking current files to return concrete implementation gaps; no upstream source revision is implied.')
                        response = {'tool_calls': []}
                        break
                    if len(calls) > 8:
                        raise FileToolError("CONTEXT_BATCH_TOO_LARGE", "Batch at most eight focused context calls")
                    context_batches += 1
                    console.show(label + " | Read/discover files", str([
                        {"tool":call["tool"],"target":call.get("path",call.get("glob","**/*"))} for call in calls]))
                    results = files.execute(calls)
                    observation = {"tool_results": results}
                    fresh_reads = [item for item in results if item.get('tool') == 'read_file'
                        and item.get('result', {}).get('content') is not None]
                    if fresh_reads:
                        files.discovery_no_progress = 0
                    elif results and all(item.get('tool') == 'read_file' and
                            item.get('result', {}).get('cached') for item in results):
                        files.discovery_no_progress += 1
                    for item in results:
                        if "error" in item or item.get("tool") != "read_file":
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
                        "read_paths": [item["result"]["path"] for item in results if "result" in item and item.get("tool")=="read_file"],
                        "tool_results": [{**item, 'result': {
                            'cache_id': item['result']['cache_id'],
                            'context_reference': 'discovery_cache[' + item['result']['cache_id'] + ']',
                            **{key: item['result'][key] for key in ('cached', 'new_evidence', 'next_action', 'no_progress_queries')
                               if key in item['result']}}}
                            if item.get('result', {}).get('cache_id') in files.discovery_cache else item
                            for item in results if item.get("tool") != "read_file"],
                        "errors": [item["error"] for item in results if "error" in item],
                        "references": [item["result"] for item in results if item.get("result", {}).get("cached")],
                    }
                    if files.discovery_no_progress >= 2:
                        console.show(label + ' | Reuse retained evidence',
                            'Repeated discovery added no evidence. Implement from the shared guide/cache or identify the exact blocker.')
                    if context_result["errors"]:
                        console.show(label + " | Read feedback (checks not run)", json.dumps(context_result["errors"], ensure_ascii=False))
                    fingerprint = json.dumps(observation, sort_keys=True, ensure_ascii=False)
                    count = read_observations.get(fingerprint, 0) + 1
                    read_observations[fingerprint] = count
                    if count >= 3:
                        files.discovery_no_progress = max(files.discovery_no_progress, 3)
                        context_result['next_action'] = 'Repeated unchanged observations. Implement now or report the exact blocker; do not repeat discovery.'
                    if count == 2:
                        context_result["next_action"] = "These read results are already retained. Use them instead of reading again."
                else:
                    break
                response = request_model()
            if isinstance(response, dict) and response.get("diagnosis"):
                console.show(label + " | Failure diagnosis", json.dumps(response["diagnosis"], ensure_ascii=False, indent=2))
            calls = response["tool_calls"]
            results = files.execute(calls)
            if any(change['before'] != change['after'] for change in files.last_changes):
                # Never present old discovery snippets after publishing application edits.
                files.discovery_cache.clear()
                files.discovery_seen.clear()
                files.discovery_no_progress = 0
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
            context_batches = 0  # A real acceptance attempt starts a fresh repair evidence budget.
            checks = gate()
            files.discovery_no_progress = 0
            checkpoint(files.output, task=label, action=f"Accept edit round {turn}",
                details={"round": turn, "checks": checks})
            return {"turns": turn, "protocol_retries": protocol_retries, "checks": checks, "files": sorted(files.changed_paths)}
        except (UpstreamRepairRequired, ProtocolExhausted, TestSetupRequired):
            raise
        except (*RESPONSE_ERRORS, RuntimeError, OSError) as error:
            message = str(error)
            phase = "acceptance" if checking else "tool_protocol"
            title = "Acceptance failed" if checking else "Tool feedback (checks not run)"
            console.show(f"{label} | {title}", message)
            if checking:
                same_tool_failure = 0
            if isinstance(error, FileToolError):
                tool_signature = (error.feedback.get('code'), error.feedback.get('path'))
                same_tool_failure = same_tool_failure + 1 if tool_signature == last_tool_failure else 1
                last_tool_failure = tool_signature
                rejected = {"error": message, "details": error.feedback}
            elif checking:
                rejected = getattr(error, "feedback", {"error": message})
            else:
                rejected = response_feedback(error, response)
            if isinstance(response, dict) and response.get("diagnosis") and isinstance(rejected, dict):
                rejected = {**rejected, "previous_diagnosis": response["diagnosis"]}
            rejected = feedback_filter(rejected) if feedback_filter else rejected
            if checking:
                signature = failure_signature(rejected)
                same_failure = same_failure + 1 if signature == last_failure else 1
                last_failure = signature
                if same_failure >= 2:
                    rejected = {'checks': rejected, 'stalled_diagnosis_required': True,
                        'instruction': 'Same failing evidence repeated. Reclassify implementation vs isolated Given/test '
                                       'vs environment; do not change production seeds or repeat the same repair.'}
            if checking:
                last_acceptance = {"origin": "agent_gate", "round": turn, "stale": False, "checks": rejected}
            feedback = [{"phase": phase, "round": turn, "acceptance_ran": checking,
                "error": message[:1600], "details": rejected,
                "next_action": "Repair the code or evidenced test issue using these fresh check results." if checking
                    else "Resolve this tool/path/target error first. No new compilation or tests ran in this round; do not infer a new business failure from stale checks."}]
            checkpoint(files.output, task=label, action=f"Reject edit round {turn}", status="REJECTED",
                details={"round": turn, "applied": applied, "phase": phase,
                    "acceptance_ran": checking, "last_acceptance_stale": last_acceptance["stale"], "feedback": feedback})
            if not checking and same_tool_failure >= 3:
                raise RepairStalled(label + ' / repeated tool misuse requires diagnosis', turn, rejected)
            if checking and same_failure >= 3:
                raise RepairStalled(label + ' / repeated failure requires diagnosis', turn, rejected)
    raise AgentExhausted(label, max_turns, feedback)
