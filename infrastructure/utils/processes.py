"""Cross-platform process startup, UTF-8 output, npm resolution, and owned-tree cleanup."""

import os
from pathlib import Path
import shutil
import signal
import subprocess

WINDOWS = os.name == "nt"


def child_environment(overrides=None) -> dict:
    """Keep inherited settings while making Python child output consistently UTF-8."""
    return {**os.environ, **(overrides or {}), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def process_options() -> dict:
    """Create an owned process group using the host platform's supported API."""
    if WINDOWS:
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)}
    return {"start_new_session": True}


def start_process(command, *, cwd, env=None, **options):
    """Launch an argument list without shell interpolation, preserving spaces and Unicode paths."""
    return subprocess.Popen([str(part) for part in command], cwd=cwd,
        env=child_environment(env), **process_options(), **options)


def stop_process(process) -> None:
    """Stop only the owned process tree on interruption/timeout, including browser/server children."""
    if WINDOWS:
        # Killing node.exe alone leaves its Playwright/Vite descendants running.
        subprocess.run([shutil.which("taskkill") or "taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        # The parent can exit before a descendant; clean the remaining group too.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def capture_process(command, *, cwd, timeout, env=None) -> dict:
    """Capture UTF-8 output and clean the whole process tree before re-raising timeout or Ctrl+C."""
    process = start_process(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException:
        stop_process(process)
        process.communicate(timeout=5)
        raise
    return {"returncode": process.returncode, "stdout": stdout,
        "output": (stdout + stderr)[-24000:]}


def npm_command() -> list[str]:
    """Resolve npm through its JavaScript CLI, avoiding Windows .cmd shell quoting."""
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        raise ValueError("Node.js and npm are required; install them and add their executables to PATH")
    node = str(Path(node).resolve())
    launcher = Path(npm).resolve()
    if launcher.suffix.lower() in {".js", ".mjs"}:
        return [node, str(launcher)]
    for directory in (launcher.parent, Path(node).resolve().parent):
        script = directory / "node_modules/npm/bin/npm-cli.js"
        if script.is_file():
            return [node, str(script)]
    if launcher.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        raise ValueError("Cannot locate npm-cli.js beside the npm/Node launcher; use a complete Node.js installation")
    # Unix installations may expose an executable script rather than a JS symlink.
    return [str(launcher)]
