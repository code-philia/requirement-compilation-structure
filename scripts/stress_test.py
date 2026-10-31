"""Launch independent background compiler jobs with isolated ports, workspaces and logs."""

import argparse
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]


def available_ports(start: int, count: int) -> list[int]:
    """Find distinct currently unused localhost ports, skipping occupied candidates."""
    ports = []
    for port in range(start, 65536):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as error:
                if error.errno == errno.EADDRINUSE:
                    continue
                raise
        ports.append(port)
        if len(ports) == count:
            return ports
    raise ValueError(f"Cannot allocate {count} available ports starting at {start}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=50, help="Number of concurrent compiler jobs (default: 50)")
    parser.add_argument("--input", type=Path, default=ROOT / "outputs/input")
    parser.add_argument("--output", type=Path, help="New stress-test directory (default: outputs/stress-TIMESTAMP)")
    parser.add_argument("--base-port", type=int, default=33000, help="First candidate backend port (default: 33000)")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--python", type=Path, default=Path(sys.executable), help="Python executable for all jobs")
    parser.add_argument("--model-log", action="store_true", help="Save detailed model I/O for each job")
    parser.add_argument("--dry-run", action="store_true", help="Write the launch plan without starting jobs")
    args = parser.parse_args(argv)
    args.input = args.input.expanduser().resolve()
    args.env_file = args.env_file.expanduser().resolve()
    # Keep the virtualenv launcher path: resolving its symlink would lose the environment.
    args.python = args.python.expanduser().absolute()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    args.output = (args.output or ROOT / "outputs" / f"stress-{timestamp}").expanduser().resolve()
    if args.count < 1 or not 1 <= args.base_port <= 65535 or args.base_port + args.count - 1 > 65535:
        parser.error("Count must be positive and the requested port range must fit within 1..65535")
    if not (args.input / "requirements.yaml").is_file():
        parser.error(f"Missing input requirement document: {args.input / 'requirements.yaml'}")
    if not args.env_file.is_file() or not args.python.is_file():
        parser.error("The environment file and Python executable must exist")
    if args.output.exists():
        parser.error(f"Choose a new output directory: {args.output}")
    if args.output == args.input or args.input in args.output.parents:
        parser.error("Output must not be inside the input directory")
    return args


def launch(args):
    """Detach jobs without waiting; persist each PID immediately for later inspection."""
    ports = available_ports(args.base_port, args.count)
    environment = {**os.environ, **{key: value for key, value in dotenv_values(args.env_file).items() if value is not None},
        "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "logs").mkdir()
    manifest = {"input": str(args.input), "env_file": str(args.env_file),
        "created_at": datetime.now(timezone.utc).isoformat(), "dry_run": args.dry_run, "jobs": []}
    for index, port in enumerate(ports, 1):
        name = f"run-{index:03d}"
        output = args.output / name
        command = [str(args.python), "-u", str(ROOT / "main.py"), str(args.input),
            "--output-dir", str(output), "--port", str(port)]
        if args.model_log:
            command.append("--model-log")
        manifest["jobs"].append({"name": name, "port": port, "output": str(output),
            "log": str(args.output / "logs" / f"{name}.log"), "command": command, "pid": None, "status": "planned"})
    path = args.output / "manifest.json"

    def save():
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    save()
    processes = []
    print(f"Manifest: {path}", flush=True)
    for job in manifest["jobs"]:
        if args.dry_run:
            print(shlex.join(job["command"]) + " > " + shlex.quote(job["log"]) + " 2>&1 < /dev/null &", flush=True)
            continue
        try:
            with open(job["log"], "x", encoding="utf-8") as stream:
                process = subprocess.Popen(job["command"], cwd=ROOT,
                    env={**environment, "PORT": str(job["port"])}, stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            processes.append(process)
            job.update(pid=process.pid, status="launched")
        except OSError as error:
            job.update(status="launch_failed", error=str(error))
            save()
            raise
        save()
        print(f"{job['name']} | PID {job['pid']} | port {job['port']} | {job['log']}", flush=True)
    print(f"{'Planned' if args.dry_run else 'Launched'} {len(ports)} jobs. Application startup uses the assigned backend ports.", flush=True)
    return manifest


def main(argv=None):
    args = parse_args(argv)
    try:
        launch(args)
    except KeyboardInterrupt:
        print(f"Launcher interrupted; already launched jobs remain running. See {args.output / 'manifest.json'}", file=sys.stderr)
        raise SystemExit(130)
    except (OSError, ValueError) as error:
        print(f"Launch failed: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
