"""Bounded JSON edit -> fixed acceptance check -> repair loop."""

from infrastructure.shared.agent.files import FileWorkspace
from infrastructure.shared.agent.protocol import FILE_EDIT_RULES


def run_file_agent(model, instructions: str, task: dict, files: FileWorkspace, gate,
        max_turns: int, console, label: str, feedback=None) -> dict:
    """Supply current files once, apply whole-file edits and accept only a passing gate."""
    if max_turns < 1:
        raise ValueError("--max-turns must be positive")
    feedback = [] if feedback is None else [feedback]
    for turn in range(1, max_turns + 1):
        try:
            response = model.generate_json(instructions + "\n\n" + FILE_EDIT_RULES,
                {"task": task, "files": files.state(), "feedback": feedback})
            files.apply(response)
            console.show(f"{label} | Edit round {turn}/{max_turns}",
                str([edit["path"] for edit in response["edits"]]))
            return {"turns": turn, "checks": gate()}
        except (ValueError, OSError) as error:
            message = str(error)
            console.show(f"{label} | Repair feedback", message)
            feedback = [{"error": message}]
    raise ValueError(f"Agent exhausted {max_turns} rounds for {label}")
