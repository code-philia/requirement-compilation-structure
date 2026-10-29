"""Bounded terminal previews with complete panel content in the workspace log."""

from contextvars import ContextVar
import os
import shutil
import sys
import textwrap

from infrastructure.utils.presentation.logging import full_detail, session_info


_activity = ContextVar("compiler_activity", default="Model request")


def current_activity() -> str:
    """Identify the latest requirement, API, page, or test operation."""
    return _activity.get()


def highlight(text: str) -> str:
    """Use color only for interactive terminals that have not disabled it."""
    if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
        return f"\033[1;36m{text}\033[0m"
    return text


def preview(body: str, max_lines: int = 22, max_chars: int = 2600) -> str:
    """Bound both long lines and many short lines; explicitly mark omitted content."""
    width = max(40, min(shutil.get_terminal_size((100, 24)).columns, 110)) - 4
    lines = []
    for line in body[:max_chars].splitlines():
        lines.extend(textwrap.wrap(line, width=width, replace_whitespace=False) or [""])
        if len(lines) > max_lines:
            break
    shortened = len(body) > max_chars or len(lines) > max_lines
    visible = "\n".join(lines[:max_lines])
    if shortened:
        visible += "\n... [preview truncated; full content is in the logs]"
    return visible or "(empty)"


class DemoConsole:
    """Show stage and activity with concise previews and optional teaching pauses."""

    def __init__(self, pause: bool = False) -> None:
        self.pause = pause

    def show(self, title: str, body: str) -> None:
        _activity.set(title)
        session = session_info()
        label = f"{session['stage']} | {title}" if session else title
        full_detail(label, body)
        print("\n" + highlight(label), flush=True)
        print(preview(body, max_lines=12, max_chars=1400), flush=True)
        if self.pause:
            try:
                input("Press Enter to continue...")
            except EOFError as error:
                raise ValueError("--pause requires an interactive input stream") from error
