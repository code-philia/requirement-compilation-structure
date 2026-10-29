"""Framed terminal previews with complete panel content in the workspace log."""

from contextvars import ContextVar
import os
import shutil
import sys
from threading import RLock
import unicodedata

from infrastructure.utils.presentation.logging import full_detail, session_info


_activity = ContextVar("compiler_activity", default="Model request")
_render_lock = RLock()
_COLORS = {"info": "36", "input": "34", "output": "35", "success": "32", "waiting": "33", "error": "31"}


def current_activity() -> str:
    """Identify the latest requirement, API, page, or test operation."""
    return _activity.get()


def highlight(text: str, tone: str = "info") -> str:
    """Use color only for interactive terminals that have not disabled it."""
    if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
        return f"\033[1;{_COLORS[tone]}m{text}\033[0m"
    return text


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


def show_panel(title: str, body: str, tone: str = "info", max_lines: int = 30, max_chars: int = 4200) -> None:
    """Print one framed block atomically so waiting messages cannot split its rows."""
    width = _width()
    def row(text):
        return "│ " + text + " " * (width - display_width(text)) + " │"
    # Titles wrap rather than hiding the requirement or API at the end.
    rows = [highlight("┌" + "─" * (width + 2) + "┐", tone)]
    rows.extend(highlight(row(line), tone) for line in _wrap(title, width))
    rows.append(highlight("├" + "─" * (width + 2) + "┤", tone))
    for line in preview(body, max_lines=max_lines, max_chars=max_chars).splitlines():
        rows.extend(row(part) for part in _wrap(line, width))
    rows.append(highlight("└" + "─" * (width + 2) + "┘", tone))
    with _render_lock:
        print("\n" + "\n".join(rows), flush=True)


def _tone(title: str) -> str:
    lower = title.lower()
    if any(word in lower for word in ("failed", "failure", "repair feedback")):
        return "error"
    if any(word in lower for word in ("green", "accepted", "complete", "saved")):
        return "success"
    if "red" in lower.split() or "waiting" in lower:
        return "waiting"
    return "info"


class DemoConsole:
    """Show stage and activity in framed previews with optional teaching pauses."""

    def __init__(self, pause: bool = False) -> None:
        self.pause = pause

    def show(self, title: str, body: str) -> None:
        _activity.set(title)
        session = session_info()
        label = f"{session['stage']} | {title}" if session else title
        full_detail(label, body)
        show_panel(label, body, tone=_tone(title))
        if self.pause:
            try:
                input("Press Enter to continue...")
            except EOFError as error:
                raise ValueError("--pause requires an interactive input stream") from error
