"""Aggregate OpenAI-compatible streams without accepting partial model proposals."""

import os


class IncompleteModelStreamError(RuntimeError):
    """A truncated response must not become a successful compiler proposal."""


def streaming_enabled() -> bool:
    return os.environ.get("LLM_STREAMING", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def complete(client, **request):
    """Return the same complete SDK envelope for either transport mode."""
    if not request.get("stream"):
        return client.chat.completions.create(**request)

    request.pop("stream")
    request.setdefault("stream_options", {"include_usage": True})
    # SDK aggregation preserves text, reasoning, tool arguments and usage. Never
    # retry a broken stream as a non-streaming request or parse partial content.
    with client.chat.completions.stream(**request) as stream:
        received = False
        for _ in stream:
            received = True
        if not received:
            raise IncompleteModelStreamError("Model stream was empty; no output accepted.")
        response = stream.get_final_completion()
    if not response.choices or any(
        choice.finish_reason not in {"stop", "tool_calls", "function_call"}
        for choice in response.choices
    ):
        raise IncompleteModelStreamError(
            "Model stream ended without a successful finish_reason; partial output discarded."
        )
    return response
