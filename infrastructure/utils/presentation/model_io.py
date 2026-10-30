"""Full SDK and HTTP model I/O audit, with concise progress on the terminal."""

from datetime import datetime, timezone
import json
import re
from time import monotonic
from uuid import uuid4
from contextvars import ContextVar

import httpx

from infrastructure.utils.presentation.console import current_activity, preview, show_panel, WaitingStatus
from infrastructure.utils.presentation.logging import session_info, full_detail
from rich.console import Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from infrastructure.utils.presentation.artifacts import proposal_kind, render_artifact, table, text


_call = ContextVar("compiler_model_call", default=None)


def _record(event: str, **data) -> None:
    """Append untruncated values; never record authentication headers."""
    call = _call.get()
    session = session_info()
    if not session or not session.get("model_log", True):
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


def _usage_summary(usage: dict) -> str:
    """Keep a compact plain-text usage line in the persistent log."""
    counts = _usage_counts(usage)
    summary = "Reported tokens | " + " | ".join(
        f"{name.lower()}: {counts[name]:,}" if counts[name] is not None else f"{name.lower()}: unavailable"
        for name in ("Input", "Cached input", "Output", "Total"))
    if counts["Reasoning"] is not None:
        summary += f"\nReasoning tokens: {counts['Reasoning']:,} | Non-reasoning output: {counts['Non-reasoning output']}"
    return summary


def _input_view(arguments):
    """Show bounded literal prompts and a file access inventory, excluding image data."""
    views = [Text(_input_summary(arguments))]
    for message in arguments.get("messages", [])[:6]:
        prompt = _message_text(message)
        views.append(Panel(Text(preview(prompt, max_lines=10, max_chars=1000)),
            title=Text(str(message.get("role", "message"))), border_style="dim blue"))
        if message.get("role") == "user":
            try:
                payload = json.loads(prompt)
            except ValueError:
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("files"), dict):
                files = table("File", "Access")
                for path, record in list(payload["files"].items())[:16]:
                    files.add_row(text(path), text("edit" if isinstance(record, dict) and record.get("writable") else "read"))
                views.append(files)
    return Group(*views)


def _usage_counts(usage):
    """Normalize provider aliases, retaining unknown values and reported zeroes."""
    def first(*values):
        return next((value for value in values if type(value) is int), None)
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    output = first(usage.get("completion_tokens"), usage.get("output_tokens"))
    reasoning = first((usage.get("completion_tokens_details") or {}).get("reasoning_tokens"))
    return {"Input": first(usage.get("prompt_tokens"), usage.get("input_tokens")),
        "Cached input": first(details.get("cached_tokens"), usage.get("prompt_cache_hit_tokens")),
        "Output": output, "Reasoning": reasoning,
        "Non-reasoning output": output - reasoning if output is not None and reasoning is not None else None,
        "Total": first(usage.get("total_tokens"))}


def _output_view(content, usage, elapsed):
    """Rendering an incomplete proposal must not change the model call outcome."""
    try:
        return _structured_output_view(content, usage, elapsed)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return Group(Text(_usage_summary(usage)), Text(f"Round-trip latency: {elapsed:.2f} s"), Text(preview(content)))


def _usage_view(usage, elapsed):
    """Usage and timing remain visible even when detailed model logging is off."""
    metrics = table("Usage / timing", "Reported value")
    for name, value in _usage_counts(usage).items():
        metrics.add_row(text(name), text(f"{value:,}" if value is not None else "unavailable"))
    metrics.add_row(text("Round-trip latency"), Text(f"{elapsed:.2f} s", style="bold cyan"))
    return metrics


def _structured_output_view(content, usage, elapsed):
    views = [_usage_view(usage, elapsed), Text("Model proposal · acceptance belongs to the current compiler pass", style="dim")]
    try:
        value = json.loads(content)
    except ValueError:
        value = None
    if isinstance(value, dict) and isinstance(value.get("edits"), list):
        edits = table("File edits", "Source lines")
        for edit in value["edits"][:16]:
            if isinstance(edit, dict):
                edits.add_row(text(edit.get("path", "?")), text(len(str(edit.get("content", "")).splitlines())))
        views.append(edits)
        for edit in value["edits"][:2]:
            if not isinstance(edit, dict) or not isinstance(edit.get("content"), str):
                continue
            path = str(edit.get("path", ""))
            extension = path.rsplit(".", 1)[-1]
            lexer = {"ts": "typescript", "tsx": "tsx", "js": "javascript", "py": "python", "sql": "sql", "json": "json"}.get(extension, "text")
            views.append(Panel(Syntax(preview(edit["content"], max_lines=10, max_chars=1200), lexer,
                theme="ansi_dark", word_wrap=True, background_color="default"), title=text(path), border_style="dim"))
    elif isinstance(value, dict) and isinstance(value.get("content"), str):
        path = str(value.get("path", "SQL proposal"))
        views.append(Panel(Syntax(preview(value["content"], max_lines=16, max_chars=1800), "sql",
            theme="ansi_dark", word_wrap=True, background_color="default"), title=text(path), border_style="dim"))
    elif isinstance(value, dict) and isinstance(value.get("contract"), dict):
        contract = table("Condition", "Description")
        for key in ("precondition", "postcondition"):
            for item in value["contract"].get(key, [])[:12]:
                contract.add_row(text(key), text(item.get("description", item) if isinstance(item, dict) else item, 600))
        views.append(contract)
    elif isinstance(value, dict):
        try:
            views.append(render_artifact(proposal_kind(value), value, context=(session_info() or {}).get("artifacts", {})))
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            views.append(Text(preview(content)))
    else:
        views.append(Text(preview(content)))
    return Group(*views)


def _count_call(usage, elapsed, failed=False):
    session = session_info()
    if session is None:
        return
    stats = session.setdefault("model_stats", {})
    stats["calls"] = stats.get("calls", 0) + 1
    stats["failed"] = stats.get("failed", 0) + int(failed)
    stats["seconds"] = stats.get("seconds", 0) + elapsed
    for key, value in _usage_counts(usage).items():
        if value is not None:
            stats[key] = stats.get(key, 0) + value
            stats[key + " reports"] = stats.get(key + " reports", 0) + 1


def show_call_totals():
    """Summarize this stage's SDK calls; cached input is a subset of input."""
    stats = (session_info() or {}).get("model_stats", {})
    if not stats:
        return
    view = table("Stage model calls", "Value", "Usage availability")
    view.add_row(text("Calls / failed"), text(f"{stats['calls']} / {stats['failed']}"), text("SDK calls; time includes retries"))
    view.add_row(text("Total round-trip time"), text(f"{stats['seconds']:.2f} s"), text("sum of calls"))
    for key in ("Input", "Cached input", "Output", "Reasoning", "Non-reasoning output", "Total"):
        view.add_row(text(key), text(f"{stats[key]:,}" if key in stats else "unavailable"),
            text(f"reported in {stats.get(key + ' reports', 0)}/{stats['calls']} calls"))
    show_panel("Stage model usage | reported counts only", view, tone="output")


def invoke(client, arguments: dict):
    """Audit one SDK call and show a static waiting message until it returns."""
    call_id = uuid4().hex
    activity = current_activity()
    session = session_info()
    label = f"{session['stage']} | {activity}" if session else activity
    token = _call.set({"id": call_id, "activity": activity})
    verbose = session is None or session.get("model_log", True)
    if verbose:
        full_detail(f"[MODEL INPUT] {label}", "\n\n".join(_message_text(message) for message in arguments.get("messages", [])))
        show_panel(f"[MODEL INPUT] {label} | call {call_id[:8]}", _input_view(arguments), tone="input")
    else:
        show_panel(f"[MODEL CALL] {label} | call {call_id[:8]}", f"Model: {arguments.get('model')}", tone="input")
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
        usage = raw.get("usage") or {}
        _count_call(usage, elapsed)
        full_detail(f"[MODEL OUTPUT] {label}", _usage_summary(usage) + f"\nRound-trip latency: {elapsed:.2f} s" + ("\n" + content if verbose else ""))
        show_panel(f"[MODEL OUTPUT] {label} | {elapsed:.2f}s",
            _output_view(content, usage, elapsed) if verbose else _usage_view(usage, elapsed), tone="output")
        return response
    except BaseException as error:
        elapsed = monotonic() - started
        _count_call({}, elapsed, failed=True)
        waiting.close()
        _record("error", elapsed_seconds=elapsed,
            error_type=type(error).__name__, message=str(error))
        show_panel(f"[MODEL FAILED] {label}", f"Round-trip latency: {elapsed:.2f} s\n{type(error).__name__}: {error}", tone="error", max_lines=12, max_chars=1800)
        raise
    finally:
        waiting.close()
        _call.reset(token)
