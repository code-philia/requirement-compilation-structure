"""Output-local Git commands and deterministic compilation checkpoints."""

import json
import os
from pathlib import Path
import subprocess
import shutil
from uuid import uuid4


IGNORE_RULES = (
    "node_modules/", "dist/", "build/", "coverage/", "test-results/", "playwright-report/",
    "backend/data/", "*.db", "*.db-wal", "*.db-shm", "*.sqlite", "*.sqlite3",
    ".env", ".env.*", "!.env.example", "compiler.log", "model_calls.jsonl", "compilation_events.jsonl", ".arc/model_logs/",
    "__pycache__/", ".venv/",
)


class GitError(RuntimeError):
    """A Git operation failed without changing compilation acceptance."""


class GitRepository:
    """Run argument-based Git commands only inside the selected output repository."""

    def __init__(self, directory):
        self.directory = Path(directory).resolve()

    def run(self, *arguments, input=None, check=True):
        env = dict(os.environ)
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
            env.pop(key, None)
        try:
            result = subprocess.run(["git", "-C", str(self.directory), *arguments], input=input,
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise GitError(f"Git command failed: {error}") from error
        if check and result.returncode:
            raise GitError(f"git {' '.join(arguments[:3])}: {result.stderr.strip() or result.stdout.strip()}")
        return result

    def require_root(self):
        if not (self.directory / ".git").exists():
            raise GitError(f"No output-local Git repository at {self.directory}")
        root = self.run("rev-parse", "--show-toplevel").stdout.strip()
        if Path(root).resolve() != self.directory:
            raise GitError("Refusing to operate on a repository outside the output directory")

    def initialize(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        if not (self.directory / ".git").exists():
            self.run("init")
        self.require_root()
        branch = self.run("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        if branch.returncode:
            raise GitError("Detached output HEAD; select a branch before compilation")
        if branch.stdout.strip() != "main":
            if self.run("rev-parse", "--verify", "HEAD", check=False).returncode:
                self.run("symbolic-ref", "HEAD", "refs/heads/main")
            else:
                self.run("branch", "-m", "main")
        ignore = self.directory / ".gitignore"
        source = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
        missing = [rule for rule in IGNORE_RULES if rule not in source.splitlines()]
        if missing:
            ignore.write_text((source.rstrip() + "\n\n" if source else "") + "# Compiler checkpoint exclusions\n"
                + "\n".join(missing) + "\n", encoding="utf-8")
        return self

    def add(self, *paths):
        self.require_root()
        return self.run("add", "-A", "--", *(paths or (".",)))

    def status(self):
        self.require_root()
        return self.run("status", "--short").stdout

    def diff(self, *, staged=False):
        self.require_root()
        return self.run("diff", *(('--cached',) if staged else ())).stdout

    def log(self, count=20):
        self.require_root()
        return self.run("log", f"-{int(count)}", "--format=%h %s").stdout

    def show(self, revision="HEAD"):
        self.require_root()
        return self.run("show", revision, "--").stdout

    def commit(self, message, *, allow_empty=True):
        self.require_root()
        options = ["-c", "commit.gpgsign=false"]
        for key, fallback in (("user.name", "Requirement Compiler"),
                              ("user.email", "compiler@localhost")):
            configured = self.run("config", "--get", key, check=False)
            if not configured.stdout.strip():
                options.extend(("-c", f"{key}={fallback}"))
        self.run(*options, "commit", *(('--allow-empty',) if allow_empty else ()), "--file=-", input=message)
        return self.run("rev-parse", "HEAD").stdout.strip()


def summarize(value):
    """Retain check outcomes and counts without copying source or full tool logs."""
    if isinstance(value, dict):
        return {str(key): summarize(child) for key, child in value.items()
            if key not in {"output", "stdout", "stderr", "content", "traceback", "previous_response", "invalid_response"}}
    if isinstance(value, (list, tuple)):
        return [summarize(child) for child in value[:30]]
    if isinstance(value, str):
        return value[:2000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:500]


def initialize_repository(output):
    """Initialize main and its first snapshot; report Git errors without stopping a pass."""
    try:
        repository = GitRepository(output).initialize()
        if repository.run("rev-parse", "--verify", "HEAD", check=False).returncode:
            checkpoint(output, stage="00", task="repository", action="Initialize output repository",
                status="READY", details={"branch": "main", "scope": "Application sources, designs, tests and reports"})
        return repository
    except (GitError, OSError) as error:
        print(f"[GIT WARNING] {error}", flush=True)
        return None


def rollback_before_stage(output: Path, previous_stage: str):
    """Restore the last previous-stage report, preserving committed history on a branch."""
    from infrastructure.shared.project.initialize import DEFAULT_STACK, STACKS

    repository = GitRepository(output)
    repository.require_root()
    branch = repository.run("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if branch.stdout.strip() != "main":
        raise GitError("Rollback requires the output repository's main branch")
    if repository.status().strip():
        raise GitError("Output repository has uncommitted or untracked files; commit or move them before rollback")

    prefix = f"[{previous_stage}] stage report: Publish pass result ("
    records = repository.run("log", "--format=%H%x09%s").stdout.splitlines()
    revision = None
    for record in records:
        commit, title = record.split("\t", 1)
        if title.startswith(prefix):
            status = title[len(prefix):].removesuffix(")")
            if status in {"FAILED", "COMPLETED_WITH_FAILURES", "INTERRUPTED", "RUNNING"}:
                raise GitError(f"Previous stage {previous_stage} did not complete successfully: {status}")
            revision = commit
            break
    if revision is None:
        raise GitError(f"No completed stage checkpoint found for {previous_stage}")

    build_directories = STACKS[DEFAULT_STACK]["build_directories"]
    for relative in build_directories:
        target = repository.directory / relative
        if not target.resolve().is_relative_to(repository.directory):
            raise GitError(f"Build output escapes the output directory: {relative}")
        tracked = repository.run("ls-tree", "-r", "--name-only", revision, "--", relative).stdout.strip()
        if tracked:
            raise GitError(f"Build output contains tracked files: {relative}")

    backup = "before-rollback-" + uuid4().hex[:12]
    repository.run("branch", backup, "HEAD")
    repository.run("reset", "--hard", revision)
    print(f"[GIT] Restored {revision[:8]}; previous HEAD saved as {backup}", flush=True)
    for relative in build_directories:
        target = repository.directory / relative
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        print(f"[BUILD] Cleared {relative}", flush=True)


def checkpoint(output=None, *, stage=None, task, action, status="GREEN", details=None):
    """Record a semantic step, including no-change checks, without hiding build failures."""
    from infrastructure.utils.presentation.logging import session_info
    session = session_info()
    if output is None:
        if session is None:
            return None
        output = session["output"]
    stage = stage or (session["stage"] if session else "compiler")
    repository = GitRepository(output)
    # Pure helper calls without an initialized workspace do not create repositories.
    if not (repository.directory / ".git").exists():
        return None
    try:
        repository.require_root()
        if repository.run("symbolic-ref", "--quiet", "--short", "HEAD", check=False).stdout.strip() != "main":
            raise GitError("Checkpoints require the output repository's main branch")
        repository.add()
        changed = repository.run("diff", "--cached", "--stat").stdout.strip()
        title = " ".join(f"[{stage}] {task}: {action} ({status})".split())
        message = (title + f"\n\nStage: {stage}\nTask: {task}\nAction: {action}\nStatus: {status}\n"
            + "\nDetails:\n" + json.dumps(summarize(details or {}), ensure_ascii=False, indent=2)
            + "\n\nChanged files:\n" + (changed or "No tracked file changes; execution checkpoint.") + "\n")
        revision = repository.commit(message)
        print(f"[GIT] {revision[:8]} {title}", flush=True)
        return revision
    except GitError as error:
        print(f"[GIT WARNING] Checkpoint failed for {task}: {error}", flush=True)
        return None
