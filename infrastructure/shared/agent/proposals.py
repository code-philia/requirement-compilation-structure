"""Retry model proposals when parsing or consuming their returned records fails."""

from itertools import count
import json


RESPONSE_ERRORS = (ValueError, KeyError, TypeError, AttributeError, IndexError)


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


def propose_json(model, instructions, request, accept, console, label, max_attempts=0):
    """Generate, consume and repair one proposal; zero attempts means retry until interrupted."""
    if max_attempts < 0:
        raise ValueError("--max-attempts must be nonnegative; use 0 for unlimited attempts")
    request = dict(request)
    for attempt in count(1):
        progress = f"{attempt}/{max_attempts}" if max_attempts else f"{attempt} (unlimited)"
        console.show(f"{label} | Model proposal {progress}", "Generate the proposal; response-reading and obligation errors receive repair feedback.")
        response = None
        try:
            response = model.generate_json(instructions, request)
            return accept(response), response
        except RESPONSE_ERRORS as error:
            feedback = response_feedback(error, response)
            console.show(f"{label} | Repair feedback", json.dumps(feedback, ensure_ascii=False, indent=2))
            if max_attempts and attempt >= max_attempts:
                raise RuntimeError(f"{label} exhausted {max_attempts} proposals: {feedback['error']}") from error
            request["correction"] = feedback
