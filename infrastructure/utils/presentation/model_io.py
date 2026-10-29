"""Full SDK and HTTP model I/O audit, with concise progress on the terminal."""

from datetime import datetime, timezone
import json
from threading import Event, Thread
from time import monotonic
from uuid import uuid4
from contextvars import ContextVar

import httpx

from infrastructure.utils.presentation.console import current_activity, highlight, preview
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


def _http_request(request: httpx.Request) -> None:
    """Capture the actual serialized body on every HTTP attempt, including retries."""
    _record("http_request", method=request.method, url=str(request.url.copy_with(query=None)),
        body=request.content.decode("utf-8"))


def _http_response(response: httpx.Response) -> None:
    """Read and retain the complete non-streaming response before SDK parsing."""
    response.read()
    _record("http_response", status_code=response.status_code,
        request_id=response.headers.get("x-request-id"), body=response.text)


def http_client() -> httpx.Client:
    """Install hooks beneath SDK retries, preserving the SDK's transport limits."""
    from openai import DefaultHttpxClient
    return DefaultHttpxClient(event_hooks={"request": [_http_request], "response": [_http_response]})


def _input_summary(arguments: dict) -> str:
    messages = arguments.get("messages", [])
    lines = [f"Model: {arguments.get('model')} | Messages: {len(messages)}"]
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            line = f"{message['role']}: {len(content):,} characters"
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
            lines.append(f"{message['role']}: text and image parts ({len(content)})")
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
                source = edit.get("content", "")
                lines.append(f"{edit.get('path', '(unknown path)')} ({len(str(source)):,} characters)")
        if len(edits) > 8:
            lines.append(f"... {len(edits) - 8} more file edits")
        for edit in edits[:3]:
            if isinstance(edit, dict) and isinstance(edit.get("content"), str):
                lines.extend([f"\n--- {edit.get('path')} ---", preview(edit["content"], max_lines=6, max_chars=650)])
        return "\n".join(lines)
    return preview(json.dumps(value, ensure_ascii=False, indent=2))


def invoke(client, arguments: dict):
    """Audit one SDK call, show raw response content, and report waiting every 10s."""
    call_id = uuid4().hex
    activity = current_activity()
    session = session_info()
    label = f"{session['stage']} | {activity}" if session else activity
    token = _call.set({"id": call_id, "activity": activity})
    started = monotonic()
    stop = Event()
    print("\n" + highlight(f"[MODEL INPUT] {label} | call {call_id[:8]}"), flush=True)
    print(preview(_input_summary(arguments), max_lines=8, max_chars=1000), flush=True)
    print("[WAITING] Waiting for model response...", flush=True)

    def heartbeat():
        while not stop.wait(10):
            print(f"[WAITING] {label} | {monotonic() - started:.0f}s elapsed (including transport retries)", flush=True)

    thread = Thread(target=heartbeat, daemon=True)
    try:
        _record("request", arguments=arguments)
        thread.start()
        response = client.chat.completions.create(**arguments)
        # Preserve the SDK envelope and untouched message content before any JSON repair.
        raw = response.model_dump(mode="json")
        _record("response", elapsed_seconds=monotonic() - started, response=raw)
        stop.set()
        thread.join()
        content = "\n".join(choice.message.content or "" for choice in response.choices)
        print(highlight(f"[MODEL OUTPUT] {label} | {monotonic() - started:.1f}s"), flush=True)
        print(_output_preview(content or json.dumps(raw, ensure_ascii=False)), flush=True)
        return response
    except BaseException as error:
        _record("error", elapsed_seconds=monotonic() - started,
            error_type=type(error).__name__, message=str(error))
        print(f"[MODEL FAILED] {label} | {type(error).__name__}: {preview(str(error), max_lines=4, max_chars=500)}", flush=True)
        raise
    finally:
        stop.set()
        if thread.is_alive():
            thread.join()
        _call.reset(token)
