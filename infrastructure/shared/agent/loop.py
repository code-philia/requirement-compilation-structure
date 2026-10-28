"""Shared model -> tool -> acceptance-gate loop for steps 08, 10, and 12.

Stage code supplies prompts, context, scoped FileTools, and a gate callback. This
module handles bounded turns and correction feedback; tests and business rules
remain the responsibility of the calling stage."""

from infrastructure.shared.agent.files import FileTools
from infrastructure.shared.agent.protocol import FILE_EDIT_RULES, TOOL_DEFINITIONS, TOOL_INSTRUCTIONS


def run_file_agent(model, instructions: str, context: dict, tools: FileTools, gate, max_turns: int, console, label: str) -> dict:
    """Run bounded model turns until the compiler accepts the edited files.

    Each turn supplies selected file contents and earlier tool/check feedback.
    An edit or finish request succeeds only when gate() accepts the result;
    rejected edits remain available for the next repair turn."""
    if max_turns < 1:
        raise ValueError("--max-turns must be positive")
    # Move declared source files into the live context to avoid stale duplicate text.
    context = dict(context)
    tools.provide_files(context.pop("source_files", {}).keys())
    history = []
    for turn in range(1, max_turns + 1):
        response = None
        try:
            # 1. Refresh compiler-selected source and ask for exactly one action.
            response = model.generate_action(instructions + "\n\nFile edit rules:\n" + FILE_EDIT_RULES + "\n\nTool protocol:\n" + TOOL_INSTRUCTIONS, {
                "context": context, "file_context": tools.state(), "history": history,
            }, TOOL_DEFINITIONS)
            if not isinstance(response, dict) or set(response) != {"tool", "arguments"} or not isinstance(response["arguments"], dict):
                raise ValueError("Return one tool action with tool and arguments")
            tool, arguments = response["tool"], response["arguments"]
            edits = arguments.get("edits", [])
            paths = arguments.get("paths", [edit.get("path") for edit in edits if isinstance(edit, dict)] if isinstance(edits, list) else [])
            console.show(f"{label} | Agent turn {turn}/{max_turns}: {tool}", str(paths))
            # 2. Execute only the shared, scoped tools; no model-chosen commands.
            value = tools.dispatch(tool, arguments)
            if tool in {"edit_files", "finish"}:
                # 3. A successful write is not acceptance: the stage owns its gate.
                accepted = gate()
                return {"turns": turn, "checks": accepted}
            history.append({"action": response, "result": value})
        except (ValueError, OSError) as error:
            # 4. Feed rejected actions/checks into the next bounded repair turn.
            feedback = str(error)
            print(f"Agent feedback ({label}): {feedback}", flush=True)
            rejected = {"action": response, "error": feedback}
            if hasattr(error, "doc"):
                rejected["invalid_response"] = error.doc[:8000]
            history.append(rejected)
    raise ValueError(f"Agent exhausted {max_turns} turns for {label}")
