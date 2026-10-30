"""Mirror step output to the terminal and an append-only workspace log."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
import sys
import re
from threading import RLock
import traceback
from contextvars import ContextVar
from time import monotonic

from infrastructure.utils.presentation.stages import stage_label


_session = ContextVar("compiler_log_session", default=None)


def session_info():
    """Return the current output directory, stage, and log lock, when configured."""
    return _session.get()


def full_detail(title: str, body: str) -> None:
    """Keep full panel content in the log without flooding the terminal."""
    session = _session.get()
    if session:
        with session["lock"]:
            session["log"].write(f"\n--- {title} (full content) ---\n{body}\n")
            session["log"].flush()


class TeeStream:
    """Stream wrapper that mirrors output to the terminal and the step log."""
    def __init__(self, terminal, log, lock) -> None:
        """Bind a terminal and log file using one lock so streamed child output remains readable."""
        self.terminal, self.log, self.lock = terminal, log, lock

    def write(self, text: str) -> int:
        """Mirror text to the terminal and log, immediately flushing the log and returning the character count."""
        with self.lock:
            self.terminal.write(text)
            self.log.write(re.sub(r"\x1b\[[0-9;]*m", "", text))
            self.log.flush()
        return len(text)

    def flush(self) -> None:
        """Flush both destinations under the shared output lock."""
        with self.lock:
            self.terminal.flush()
            self.log.flush()

    def __getattr__(self, name):
        """Delegate stream capabilities such as isatty to the original terminal."""
        return getattr(self.terminal, name)


def configure_console() -> None:
    """Use UTF-8 for real terminal/redirected streams while leaving capture streams usable."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


@contextmanager
def console_log(output_dir: Path, *, debug_model_io: bool = False):
    """Append a timestamped step session to compiler.log while mirroring stdout/stderr and recording uncaught failures."""
    from infrastructure.utils.presentation.console import show_panel
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_console()
    with (output_dir / "compiler.log").open("a", encoding="utf-8", newline="\n") as log:
        lock = RLock()
        stdout = TeeStream(sys.stdout, log, lock)
        stderr = TeeStream(sys.stderr, log, lock)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            script = Path(sys.argv[0]).name
            token = _session.set({"output": output_dir, "stage": stage_label(script), "lock": lock, "log": log,
                "debug_model_io": debug_model_io})
            started = monotonic()
            show_panel(f"[START] {stage_label(script)}", f"{timestamp}\nScript: {script}\nLogs: {output_dir / 'compiler.log'}\nFull model I/O: {output_dir / 'model_calls.jsonl'}")
            try:
                yield
            except BaseException as error:
                if not isinstance(error, SystemExit):
                    traceback.print_exc(file=log)
                show_panel(f"[FAILED] {stage_label(script)}", f"Stopped after {monotonic() - started:.1f}s", tone="error")
                raise
            else:
                show_panel(f"[DONE] {stage_label(script)}", f"Completed in {monotonic() - started:.1f}s", tone="success")
            finally:
                stdout.flush()
                stderr.flush()
                _session.reset(token)
