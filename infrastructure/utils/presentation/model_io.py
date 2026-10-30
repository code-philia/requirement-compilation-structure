"""Full SDK and HTTP model I/O audit, with concise progress on the terminal."""

from datetime import datetime, timezone
import json
import re
from time import monotonic
from uuid import uuid4
from contextvars import ContextVar

import httpx

from infrastructure.utils.presentation.console import current_activity, preview, show_panel, WaitingStatus
from infrastructure.utils.presentation.logging import session_info


_call = ContextVar("compiler_model_call", default=None)


def _record(event: str, **data) -> None:
    """Append untruncated values; never record authentication headers."""
    call = _call.get()
    session = session_info()
    if not session:
        return
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": session["stage"], "call_id": call["id"] if call else None,
        "activity": call["activity"] if call else current_activity(), "event": event, **data}
    with session["lock"]:
        with (session["output"] / "model_calls.jsonl").open("a", encoding="utf-8", newline="\n") as log:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")


def _message_text(message: dict) -> str:
    """Return message text verbatim, without the transport JSON envelope."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part["text"] for part in content if part.get("type") == "text")
    return ""


def _http_request(request: httpx.Request) -> None:
    """Capture the actual serialized body on every HTTP attempt, including retries."""
    session, call = session_info(), _call.get()
    if session and session.get("debug_model_io") and call:
        call["attempt"] = call.get("attempt", 0) + 1
        stage = session["stage"].split(" | ", 1)[0].removeprefix("Stage ")
        task = re.sub(r"[^\w.-]+", "_", call["activity"].split(" | ", 1)[0]).strip("._")[:24] or "model"
        directory = session["output"] / ".arc" / "model_logs"
        directory.mkdir(parents=True, exist_ok=True)
        prefix = directory / f"{stage.replace(' ', '_')}.{task}.{call['id'][:8]}.{call['attempt']}"
        request.extensions["compiler_model_log_prefix"] = prefix
        messages = json.loads(request.content).get("messages", [])
        text = "\n\n".join(_message_text(message) for message in messages)
        prefix.with_name(prefix.name + ".model.input").write_text(text, encoding="utf-8", newline="\n")
    _record("http_request", method=request.method, url=str(request.url.copy_with(query=None)),
        body=request.content.decode("utf-8"))


def _http_response(response: httpx.Response) -> None:
    """Read and retain the complete non-streaming response before SDK parsing."""
    response.read()
    prefix = response.request.extensions.get("compiler_model_log_prefix")
    if prefix is not None:
        try:
            body = response.json()
        except ValueError:
            text = response.text
        else:
            if isinstance(body, dict) and "choices" in body:
                text = "\n\n".join(_message_text(choice.get("message", {})) for choice in body["choices"])
            elif isinstance(body, dict) and isinstance(body.get("error"), dict):
                text = str(body["error"].get("message", ""))
            else:
                text = response.text
        prefix.with_name(prefix.name + ".model.ouput").write_text(text, encoding="utf-8", newline="\n")
    _record("http_response", status_code=response.status_code,
        request_id=response.headers.get("x-request-id"), body=response.text)


def http_client() -> httpx.Client:
    """Connect directly, retaining audit hooks and the SDK's transport limits."""
    from openai import DefaultHttpxClient
    return DefaultHttpxClient(trust_env=False,
        event_hooks={"request": [_http_request], "response": [_http_response]})


def _input_summary(arguments: dict) -> str:
    messages = arguments.get("messages", [])
    lines = [f"Model: {arguments.get('model')} | Messages: {len(messages)}"]
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            line = str(message["role"])
            if message["role"] == "user":
                try:
                    payload = json.loads(content)
                except ValueError:
                    payload = None
                if isinstance(payload, dict):
                    line += " | sections: " + ", ".join(payload)
                    files = payload.get("files")
                    if isinstance(files, dict):
                        writable = sum(bool(item.get("writable")) for item in files.values() if isinstance(item, dict))
                        line += f" | files: {len(files)} ({writable} writable)"
            lines.append(line)
        else:
            images = sum(part.get("type") == "image_url" for part in content)
            lines.append(f"{message['role']}: text and images | images: {images}")
    return "\n".join(lines)


def _output_preview(content: str) -> str:
    """Show readable JSON or source excerpts, including the affected file paths."""
    try:
        value = json.loads(content)
    except ValueError:
        return preview(content)
    if isinstance(value, dict) and isinstance(value.get("edits"), list):
        edits = value["edits"]
        lines = [f"File edits: {len(edits)}"]
        for edit in edits[:8]:
            if isinstance(edit, dict):
                lines.append(str(edit.get("path", "(unknown path)")))
        if len(edits) > 8:
            lines.append(f"... {len(edits) - 8} more file edits")
        for edit in edits[:3]:
            if isinstance(edit, dict) and isinstance(edit.get("content"), str):
                lines.extend([f"\n--- {edit.get('path')} ---", preview(edit["content"], max_lines=12, max_chars=1400)])
        return "\n".join(lines)
    return preview(json.dumps(value, ensure_ascii=False, indent=2), max_lines=40, max_chars=6000)


def _usage_summary(usage: dict) -> str:
    """Show reported usage, preserving zero counts and distinguishing absent values."""
    def first_count(*values):
        return next((value for value in values if type(value) is int), None)

    input_tokens = first_count(usage.get("prompt_tokens"), usage.get("input_tokens"))
    output_tokens = first_count(usage.get("completion_tokens"), usage.get("output_tokens"))
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached_tokens = first_count(details.get("cached_tokens"), usage.get("prompt_cache_hit_tokens"))
    counts = [("input", input_tokens), ("cached input", cached_tokens),
        ("output", output_tokens), ("total", first_count(usage.get("total_tokens")))]
    lines = ["Reported tokens | " + " | ".join(
        f"{name}: {value:,}" if value is not None else f"{name}: unavailable"
        for name, value in counts)]
    return "\n".join(lines)


def invoke(client, arguments: dict):
    """Audit one SDK call and show a static waiting message until it returns."""
    call_id = uuid4().hex
    activity = current_activity()
    session = session_info()
    label = f"{session['stage']} | {activity}" if session else activity
    token = _call.set({"id": call_id, "activity": activity})
    show_panel(f"[MODEL INPUT] {label} | call {call_id[:8]}", _input_summary(arguments), tone="input", max_lines=12, max_chars=1600)
    waiting = WaitingStatus()
    started = monotonic()

    try:
        _record("request", arguments=arguments)
        started = monotonic()
        response = client.chat.completions.create(**arguments)
        elapsed = monotonic() - started
        # Preserve the SDK envelope and untouched message content before any JSON repair.
        raw = response.model_dump(mode="json")
        _record("response", elapsed_seconds=elapsed, response=raw)
        waiting.close()
        content = "\n".join(choice.message.content or "" for choice in response.choices)
        summary = _usage_summary(raw.get("usage") or {})
        show_panel(f"[MODEL OUTPUT] {label} | {elapsed:.2f}s",
            summary + f"\nRound-trip latency: {elapsed:.2f} s\n" + _output_preview(content or json.dumps(raw, ensure_ascii=False)), tone="output", max_lines=60, max_chars=8500)
        return response
    except BaseException as error:
        elapsed = monotonic() - started
        waiting.close()
        _record("error", elapsed_seconds=elapsed,
            error_type=type(error).__name__, message=str(error))
        show_panel(f"[MODEL FAILED] {label}", f"Round-trip latency: {elapsed:.2f} s\n{type(error).__name__}: {error}", tone="error", max_lines=12, max_chars=1800)
        raise
    finally:
        waiting.close()
        _call.reset(token)
