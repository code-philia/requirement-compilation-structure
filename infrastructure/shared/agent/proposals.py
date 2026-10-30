"""Retry model proposals when parsing or consuming their returned records fails."""

import json


RESPONSE_ERRORS = (ValueError, KeyError, TypeError, AttributeError, IndexError)
REPAIR_INSTRUCTIONS = """The previous proposal was rejected. Read correction.error and correction.details
in the input and fix that failure. correction.previous_response is the rejected
answer, not an accepted example. Return a complete replacement JSON object in the
original output format, including every required top-level section. Do not return
only the unchanged portion, a partial patch, or the correction metadata itself."""


def response_feedback(error, response):
    """Describe an actual response-consumption failure, without adding design rules."""
    message = str(error)
    if isinstance(error, KeyError):
        key = error.args[0] if error.args else "(unknown)"
        message = f"Missing key {key!r} while reading the model response. Return the requested complete records."
    feedback = {"error": message, "error_type": type(error).__name__, "previous_response": response}
    if isinstance(error, json.JSONDecodeError):
        feedback["invalid_response"] = error.doc
    if hasattr(error, "feedback"):
        feedback["details"] = error.feedback
    return feedback


def propose_json(model, instructions, request, accept, console, label, max_attempts=5):
    """Generate and repair a proposal within a finite total model-call budget."""
    if max_attempts < 1:
        raise ValueError("--max-attempts must be positive")
    request = dict(request)
    for attempt in range(1, max_attempts + 1):
        progress = f"{attempt}/{max_attempts}"
        console.show(f"{label} | Model proposal {progress}", "Generate the proposal; response-reading and obligation errors receive repair feedback.")
        response = None
        try:
            prompt = instructions if "correction" not in request else instructions + "\n\n" + REPAIR_INSTRUCTIONS
            response = model.generate_json(prompt, request)
            return accept(response), response
        except RESPONSE_ERRORS as error:
            feedback = response_feedback(error, response)
            feedback["failed_attempt"] = attempt
            console.show(f"{label} | Repair feedback", json.dumps(feedback, ensure_ascii=False, indent=2))
            if attempt >= max_attempts:
                raise RuntimeError(f"{label} exhausted {max_attempts} proposals: {feedback['error']}") from error
            request["correction"] = feedback
