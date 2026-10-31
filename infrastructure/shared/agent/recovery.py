"""Isolate failed implementation tasks and complete independent final checks."""

from contextlib import contextmanager
import re
from uuid import uuid4

from infrastructure.shared.agent.files import EXCLUDED
from infrastructure.utils.files import save_bytes, save_json


def _snapshot(output):
    paths = {path.relative_to(output).as_posix()
        for root in ("backend/src", "backend/tests", "frontend/src", "frontend/tests")
        for path in (output / root).rglob("*") if path.is_file() and not path.is_symlink()
        and not any(part in EXCLUDED or part.startswith(".") for part in path.relative_to(output).parts)}
    index = ".arc/implementation_paths.json"
    if (output / index).is_file():
        paths.add(index)
    return {path: (output / path).read_bytes() for path in paths}


@contextmanager
def implementation_task(output, entry, console, label):
    """Archive rejected files, restore the task baseline, and continue on acceptance failure.

    Missing prerequisites are checked before this boundary. Disk errors, interrupts,
    and unexpected compiler exceptions propagate; they are not business failures.
    """
    before = _snapshot(output)
    try:
        yield
    except ValueError as error:
        after = _snapshot(output)
        changed = {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
        name = re.sub(r"[^\w.-]+", "_", label).strip("._")[:100] or "task"
        directory = output / ".arc/failures" / f"{name}.{uuid4().hex[:8]}"
        for path in sorted(changed):
            if path in after:
                save_bytes(directory / "files" / path, after[path])
        failure = {"status": "FAILED", "task": label, "phase": entry.get("status"),
            "error": str(error), "turns": getattr(error, "turns", 0),
            "feedback": getattr(error, "feedback", None), "changed_files": sorted(changed),
            "deleted_files": sorted(changed - after.keys()),
            "archive": directory.relative_to(output).as_posix()}
        save_json(directory / "failure.json", failure)
        for path in sorted(changed):
            if path in before:
                save_bytes(output / path, before[path])
            else:
                (output / path).unlink(missing_ok=True)
        entry.update(failure)
        console.show(label + " | FAILED; continuing", str(error) + "\nBaseline restored. Failure archive: " + failure["archive"])


def final_checks(console, **checks):
    """Attempt every final compiler/test/build check even if an earlier check fails."""
    results = {}
    for name, (action, accept) in checks.items():
        result = None
        try:
            result = action()
            if result.get("returncode"):
                raise ValueError(result.get("output", f"{name} failed"))
            if accept:
                accept(result)
            results[name] = {"status": "GREEN", "result": result}
        except (ValueError, RuntimeError) as error:
            results[name] = {"status": "FAILED", "result": result, "error": str(error)}
        console.show("Final verification | " + name + " | " + results[name]["status"],
            results[name].get("error") or (result or {}).get("output", "Passed"))
    return results


def complete_report(report, entries, verification):
    """Separate completion of the process from successful acceptance."""
    report["failures"] = [dict(entry) for entry in entries if entry.get("status") == "FAILED"]
    report["verification"] = verification
    report["status"] = ("COMPLETED_WITH_FAILURES" if report["failures"]
        or any(check["status"] == "FAILED" for check in verification.values()) else "GREEN")
    return report
