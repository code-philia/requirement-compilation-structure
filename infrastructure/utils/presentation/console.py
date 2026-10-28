"""Render teaching panels and optionally pause for classroom discussion."""

import shutil
import textwrap


class DemoConsole:
    """Readable classroom panels with an optional pause after each displayed stage."""
    def __init__(self, pause: bool = False) -> None:
        """Remember whether each teaching panel should wait for Enter."""
        self.pause = pause

    def show(self, title: str, body: str) -> None:
        """Print a width-limited teaching panel and, when requested, pause on interactive input."""
        width = max(40, min(shutil.get_terminal_size((100, 24)).columns, 110)) - 4
        print("\n┌" + "─" * (width + 2) + "┐")
        print("│ " + title[:width].ljust(width) + " │")
        print("├" + "─" * (width + 2) + "┤")
        for line in body.splitlines() or [""]:
            for wrapped in textwrap.wrap(line, width=width, replace_whitespace=False) or [""]:
                print("│ " + wrapped.ljust(width) + " │")
        print("└" + "─" * (width + 2) + "┘", flush=True)
        if self.pause:
            try:
                input("Press Enter to continue...")
            except EOFError as error:
                raise ValueError("--pause requires an interactive input stream") from error
