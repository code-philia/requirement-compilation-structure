"""Mirror step output to the terminal and an append-only workspace log."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
import sys
from threading import RLock
import traceback


class TeeStream:
    """Stream wrapper that mirrors output to the terminal and the step log."""
    def __init__(self, terminal, log, lock) -> None:
        """Bind a terminal and log file using one lock so streamed child output remains readable."""
        self.terminal, self.log, self.lock = terminal, log, lock

    def write(self, text: str) -> int:
        """Mirror text to the terminal and log, immediately flushing the log and returning the character count."""
        with self.lock:
            self.terminal.write(text)
            self.log.write(text)
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


@contextmanager
def console_log(output_dir: Path):
    """Append a timestamped step session to compiler.log while mirroring stdout/stderr and recording uncaught failures."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "compiler.log").open("a", encoding="utf-8") as log:
        lock = RLock()
        stdout = TeeStream(sys.stdout, log, lock)
        stderr = TeeStream(sys.stderr, log, lock)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            print(f"\n=== {timestamp} | {Path(sys.argv[0]).name} ===", flush=True)
            try:
                yield
            except BaseException as error:
                if not isinstance(error, SystemExit):
                    traceback.print_exc(file=log)
                raise
            finally:
                stdout.flush()
                stderr.flush()
