"""Bounded JSON edit -> fixed acceptance check -> repair loop."""

from infrastructure.shared.agent.files import FileWorkspace
from infrastructure.shared.agent.protocol import FILE_EDIT_RULES
from infrastructure.shared.agent.proposals import RESPONSE_ERRORS, response_feedback


def run_file_agent(model, instructions: str, task: dict, files: FileWorkspace, gate,
        max_turns: int, console, label: str, feedback=None, feedback_filter=None) -> dict:
    """Refresh files and paths; optionally select failure-related files before repair.

    The stage-owned feedback filter may add writable sources/read-only references
    and condense check reports. It cannot change the acceptance gate or its result.
    """
    if max_turns < 1:
        raise ValueError("--max-turns must be positive")
    feedback = [] if feedback is None else [feedback_filter(feedback) if feedback_filter else feedback]
    for turn in range(1, max_turns + 1):
        console.show(f"{label} | Edit round {turn}/{max_turns}",
            "Generate file edits, then run the stage's compilation and test acceptance checks.")
        response, applied = None, False
        try:
            response = model.generate_json(instructions + "\n\n" + FILE_EDIT_RULES,
                {"task": files.task_state(task), "files": files.state(), "feedback": feedback})
            files.apply(response)
            applied = True
            if files.new_file is not None:
                raise ValueError("Create the target file in the first edit before running acceptance checks")
            console.show(f"{label} | Edit round {turn}/{max_turns}",
                str([edit["path"] for edit in response["edits"]]))
            return {"turns": turn, "checks": gate()}
        except (*RESPONSE_ERRORS, OSError) as error:
            message = str(error)
            console.show(f"{label} | Repair feedback", message)
            rejected = (getattr(error, "feedback", {"error": message}) if applied
                else response_feedback(error, response))
            feedback = [feedback_filter(rejected) if feedback_filter else rejected]
    raise ValueError(f"Agent exhausted {max_turns} rounds for {label}")
