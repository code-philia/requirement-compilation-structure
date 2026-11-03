"""Run one compiler in an isolated process; publish stage events and artifact snapshots."""

import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from metrics import read_json, write_json

ARTIFACTS = (
    "requirements",
    "visual_analysis",
    "db_schema",
    "db_obligations",
    "db_implementations",
    "backend_apis",
    "backend_tdd",
    "ui_design",
    "ui_checks",
    "frontend_triggers",
    "frontend_e2e",
    "independent_acceptance",
    "compilation",
)


def now():
    return datetime.now(timezone.utc).isoformat()


def main():
    config = json.loads(sys.stdin.readline())
    run_dir = Path(config["run_dir"])
    output = Path(config["output"])
    manifest = read_json(run_dir / "run.json")
    for key, value in config["environment"].items():
        if value is not None:
            os.environ[key] = value
    # An omitted visual override must follow the selected text configuration,
    # rather than silently using a different provider from compiler/.env.
    os.environ.setdefault("VISUAL_MODEL", os.environ["MODEL"])
    os.environ.setdefault("VISUAL_API_KEY", os.environ["OPENAI_API_KEY"])
    os.environ.setdefault("VISUAL_BASE_URL", os.environ["OPENAI_BASE_URL"])
    from infrastructure.compiler import Compiler
    from infrastructure.shared.project.git import GitRepository

    # Keep the run archive out of compiler-owned application checkpoints.
    GitRepository(output).initialize()
    exclude = output / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text() if exclude.exists() else ""
    if "/.arc/playground/" not in existing.splitlines():
        exclude.write_text(existing.rstrip() + "\n/.arc/playground/\n")

    lock = threading.RLock()
    stopped = threading.Event()
    signatures = {}
    model_offset = config.get("model_offset", 0)

    def event(kind, **data):
        with lock:
            record = {"type": kind, "timestamp": now(), **data}
            with (run_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def snapshot():
        nonlocal model_offset
        with lock:
            source = output / "model_calls.jsonl"
            try:
                with source.open("rb") as stream:
                    stream.seek(model_offset)
                    chunk = stream.read()
                # Keep an incomplete JSONL tail for the next observation.
                boundary = chunk.rfind(b"\n") + 1
                if boundary:
                    with (run_dir / "model_calls.jsonl").open("ab") as target:
                        captured = chunk[:boundary]
                        for key, value in config["environment"].items():
                            if "KEY" in key and value:
                                captured = captured.replace(
                                    value.encode(), b"[REDACTED]"
                                )
                        target.write(captured)
                    model_offset += boundary
            except OSError:
                pass
            for name in ARTIFACTS:
                path = output / ".arc" / (name + ".json")
                try:
                    signature = (path.stat().st_mtime_ns, path.stat().st_size)
                    if signatures.get(name) == signature:
                        continue
                    value = json.loads(path.read_text(encoding="utf-8-sig"))
                    write_json(run_dir / "artifacts" / (name + ".json"), value)
                    signatures[name] = signature
                    event("artifact", artifact=name)
                except (OSError, ValueError):
                    continue

    def watch():
        while not stopped.wait(0.7):
            snapshot()

    class ObservedCompiler(Compiler):
        def _run(self, stage, function, *arguments, **options):
            started = time.monotonic()
            with lock:
                manifest["stages"][stage] = {"status": "RUNNING", "started_at": now()}
                write_json(run_dir / "run.json", manifest)
            event("stage_started", stage=stage)
            try:
                result = super()._run(stage, function, *arguments, **options)
                return result
            finally:
                with lock:
                    entry = manifest["stages"][stage]
                    entry.update(self.report["stages"].get(stage, {"status": "FAILED"}))
                    entry.update(finished_at=now(), seconds=time.monotonic() - started)
                    write_json(run_dir / "run.json", manifest)
                snapshot()
                event("stage_finished", stage=stage, status=entry["status"])

    # Copy prerequisites once so single-stage runs retain an honest starting state.
    snapshot()
    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    compiler = ObservedCompiler(
        Path(config["input"]),
        output,
        model_log=True,
        port=config.get("port", 3000),
        pause=False,
    )
    started = time.monotonic()
    try:
        compiler.compile(stage=config.get("stage") or None)
        manifest["status"] = compiler.report["status"]
    except KeyboardInterrupt:
        manifest["status"] = "INTERRUPTED"
    except BaseException as error:
        manifest.update(status="FAILED", error=str(error))
        import traceback

        traceback.print_exc()
    finally:
        stopped.set()
        watcher.join(timeout=3)
        snapshot()
        manifest.update(finished_at=now(), seconds=time.monotonic() - started)
        write_json(run_dir / "run.json", manifest)
        event("run_finished", status=manifest["status"])


if __name__ == "__main__":
    main()
