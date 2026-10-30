"""Framed terminal previews with complete panel content in the workspace log."""

from contextvars import ContextVar
import os
import shutil
import sys
from threading import RLock
import unicodedata
import json
from copy import deepcopy

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from infrastructure.utils.presentation.logging import full_detail, session_info


_activity = ContextVar("compiler_activity", default="Model request")
_render_lock = RLock()
_COLORS = {"info": "cyan", "input": "blue", "output": "magenta", "success": "green", "waiting": "yellow", "error": "red"}


def current_activity() -> str:
    """Identify the latest requirement, API, page, or test operation."""
    return _activity.get()


def rich_console() -> Console:
    """Bind to the current stream so redirection and plain log mirroring still work."""
    interactive = sys.stdout.isatty()
    return Console(file=sys.stdout, width=_width() + 4, force_terminal=interactive,
        color_system="standard" if interactive and "NO_COLOR" not in os.environ else None,
        highlight=False, markup=False)


def display_width(text: str) -> int:
    """Measure terminal columns, including wide CJK and combining characters."""
    return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        for char in text)


def _width() -> int:
    return max(12, min(shutil.get_terminal_size((100, 24)).columns - 4, 106))


def _wrap(line: str, width: int) -> list[str]:
    lines, current, columns = [], "", 0
    for char in line.expandtabs(4):
        size = display_width(char)
        if current and columns + size > width:
            lines.append(current)
            current, columns = "", 0
        current += char
        columns += size
    return [*lines, current]


def preview(body: str, max_lines: int = 30, max_chars: int = 4200) -> str:
    """Bound both long lines and many short lines; explicitly mark omitted content."""
    lines = []
    for line in body[:max_chars].splitlines():
        lines.extend(_wrap(line, _width()))
        if len(lines) > max_lines:
            break
    shortened = len(body) > max_chars or len(lines) > max_lines
    visible = "\n".join(lines[:max_lines])
    if shortened:
        visible += "\n... [preview truncated; full content is in the logs]"
    return visible or "(empty)"


def show_panel(title: str, body, tone: str = "info", max_lines: int = 30, max_chars: int = 4200) -> None:
    """Print literal text or a Rich view atomically, retaining scrollback."""
    if isinstance(body, str):
        body = Text(preview(body, max_lines=max_lines, max_chars=max_chars))
    style = _COLORS.get(tone, "cyan")
    panel = Panel(Group(Text(title, style="bold " + style), Rule(style=style), body),
        border_style=style, box=box.SQUARE, padding=(0, 1), expand=True)
    with _render_lock:
        rich_console().print(panel)


def _tone(title: str) -> str:
    lower = title.lower()
    if any(word in lower for word in ("failed", "failure", "repair feedback")):
        return "error"
    if any(word in lower for word in ("green", "accepted", "complete", "saved")):
        return "success"
    if "red" in lower.split() or "waiting" in lower:
        return "waiting"
    return "info"


class WaitingStatus:
    """Animate waiting on terminals, keeping cursor controls out of compiler.log."""

    def __init__(self) -> None:
        from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
        self.closed = False
        self.progress = None
        message = "[WAITING] Waiting for model response..."
        terminal = getattr(sys.stdout, "terminal", sys.stdout)
        if sys.stdout.isatty():
            session = session_info()
            if session:
                with session["lock"]:
                    session["log"].write(message + "\n")
                    session["log"].flush()
            console = Console(file=terminal, width=_width() + 4, force_terminal=True,
                color_system="standard" if "NO_COLOR" not in os.environ else None, markup=False)
            self.progress = Progress(SpinnerColumn(style="cyan"), TextColumn("{task.description}"),
                TimeElapsedColumn(), console=console, transient=True, refresh_per_second=4,
                redirect_stdout=False, redirect_stderr=False)
            self.progress.add_task(Text(message), total=None)
            self.progress.start()
        else:
            print(message, flush=True)

    def close(self) -> None:
        with _render_lock:
            if self.closed:
                return
            self.closed = True
            if self.progress is not None:
                self.progress.stop()


class DemoConsole:
    """Show stage and activity in framed previews with optional teaching pauses."""

    def __init__(self, pause: bool = False) -> None:
        self.pause = pause
        self.artifacts = {}

    def show(self, title: str, body: str) -> None:
        _activity.set(title)
        session = session_info()
        label = f"{session['stage']} | {title}" if session else title
        full_detail(label, body)
        try:
            value = json.loads(body)
        except (ValueError, TypeError):
            value = None
        if isinstance(value, dict):
            from infrastructure.utils.presentation.artifacts import proposal_kind, render_artifact
            kind = proposal_kind(value)
            if kind:
                try:
                    body = render_artifact(kind, value)
                except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
                    pass
        show_panel(label, body, tone=_tone(title))
        self._wait()

    def _wait(self) -> None:
        """Apply the same teaching pause to text and artifact panels."""
        if self.pause:
            try:
                input("Press Enter to continue...")
            except EOFError as error:
                raise ValueError("--pause requires an interactive input stream") from error

    def artifact(self, kind: str, data: dict, title: str = "Accepted artifact") -> None:
        """Observe accepted state without changing stage validation or persistence."""
        from infrastructure.utils.presentation.artifacts import render_artifact
        session = session_info()
        context = session.setdefault("artifacts", {}) if session else self.artifacts
        previous = context.get(kind)
        full_detail(title + " | " + kind, json.dumps(data, ensure_ascii=False, indent=2))
        try:
            view = render_artifact(kind, data, previous, context)
            show_panel(title + " | " + kind, view, tone="success")
            context[kind] = deepcopy(data)
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
            show_panel(title, "Artifact preview unavailable: " + str(error), tone="waiting")
        self._wait()


def show_dashboard(stage: str, artifacts: dict) -> None:
    """Show the current pass and saved/in-memory artifact inventory, without inferring success."""
    from infrastructure.utils.presentation.artifacts import ARTIFACTS, inventory, table, text
    number = stage.removeprefix("Stage ").split(" | ", 1)[0]
    passes = Text()
    names = {"00": "Init", "01": "Requirements", "02": "Schema", "03": "R/W", "04": "Review*",
        "05": "SQL", "06": "APIs + P/Q", "07": "API review", "08": "Backend TDD", "09": "UI",
        "10": "UI TDD", "11": "Triggers", "12": "E2E"}
    for index, (key, name) in enumerate(names.items()):
        if index:
            passes.append(" → ", style="dim")
        passes.append(key + " " + name, style="bold cyan" if key == number else "dim")
    counts = table("Intermediate artifact", "Records", "Availability")
    for kind, label in ARTIFACTS.items():
        value = artifacts.get(kind)
        try:
            count = len(inventory(kind, value)) if value is not None else "—"
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            count = "—"
        counts.add_row(text(label), text(count),
            Text("available" if value is not None else "pending", style="green" if value is not None else "dim"))
    show_panel("Requirement compiler | " + stage, Group(passes, counts))
