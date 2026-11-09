"""Bounded Bash diagnostics in a disposable, scope-filtered Linux sandbox.

Application changes are published only by edit_file. Shell writes stay in scratch.
Never fall back to running untrusted commands on the compiler host.
"""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile

from .files import FileToolError


def bash(files, command, timeout_seconds=30):
    if not isinstance(command, str) or not command.strip() or len(command) > 8000:
        raise FileToolError("INVALID_COMMAND", "Use a nonempty command of at most 8000 characters")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
        raise FileToolError("INVALID_TIMEOUT", "Use 1 <= timeout_seconds <= 120")
    bwrap = shutil.which("bwrap")
    if not bwrap or not Path('/bin/bash').is_file():
        raise FileToolError("SHELL_UNAVAILABLE", "Bash diagnostics require Linux bubblewrap; no host-shell fallback")
    with tempfile.TemporaryDirectory(prefix="arc-agent-shell-") as directory:
        scratch = Path(directory) / "workspace"
        scratch.mkdir()
        # Include only authorized files, never .env, compiler state or host credentials.
        size = 0
        for relative in sorted(files.available_paths | files.files):
            if not files.can_read(relative):
                continue
            source = files.path(relative)
            if not source.is_file():
                continue
            size += source.stat().st_size
            if size > 64_000_000:
                raise FileToolError("SHELL_SCOPE_TOO_LARGE", "Use scoped file tools; shell snapshot exceeds 64 MB")
            target = scratch / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        args = [bwrap, "--die-with-parent", "--unshare-all", "--new-session",
            "--tmpfs", "/", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
        for system in ("/usr", "/bin", "/lib", "/lib64"):
            if Path(system).exists():
                args += ["--ro-bind", system, system]
        args += ["--bind", str(scratch), "/workspace"]
        # Installed dependencies are read-only; installation/network remain host-owned.
        dependencies = files.output / "node_modules"
        if dependencies.is_dir() and not dependencies.is_symlink():
            args += ["--ro-bind", str(dependencies), "/workspace/node_modules"]
        node = shutil.which("node")
        if node:
            args += ["--dir", "/tools", "--ro-bind", str(Path(node).resolve()), "/tools/node"]
        args += ["--clearenv", "--setenv", "PATH", "/tools:/usr/local/bin:/usr/bin:/bin",
            "--setenv", "HOME", "/tmp", "--setenv", "CI", "1", "--chdir", "/workspace",
            "/bin/bash", "--noprofile", "--norc", "-c", command]
        # Drain output while running: no unbounded communicate() buffer or log file.
        import selectors
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True, env={"PATH": os.defpath})
        import time
        deadline = time.monotonic() + timeout_seconds
        captured = bytearray()
        total = 0
        timed_out = False
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    if time.monotonic() >= deadline:
                        timed_out = True
                        break
                    for key, _ in selector.select(min(0.2, max(0, deadline-time.monotonic()))):
                        chunk = os.read(key.fileobj.fileno(), 8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(chunk)
                        captured.extend(chunk[:max(0, 24000-len(captured))])
            if not timed_out:
                try:
                    process.wait(timeout=max(0.01, deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    timed_out = True
        finally:
            # Also clean up descendants if bash exits with background jobs alive.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            process.stdout.close()
        return {"command": command, "exit_code": process.returncode, "timed_out": timed_out,
            "output": captured.decode("utf-8", errors="replace"), "truncated": total > len(captured),
            "writes": "discarded; use edit_file to publish changes", "acceptance_ran": False}
