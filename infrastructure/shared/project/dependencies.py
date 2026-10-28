"""Install the generated workspace's npm dependencies before each TDD run."""

from pathlib import Path
import shutil
import subprocess
from threading import Thread


def install_dependencies(output_dir: Path) -> None:
    """Run npm install in the generated workspace, stream its output, and fail on timeout or nonzero exit."""
    if not (output_dir / "package.json").is_file():
        raise ValueError("Run 00_project_initialization.py before installing project dependencies")
    npm = shutil.which("npm")
    if npm is None:
        raise ValueError("npm is not available; install Node.js and npm first")
    print(f"Installing dependencies in {output_dir}: npm install --include=dev --no-audit --no-fund", flush=True)
    with subprocess.Popen(
        [npm, "install", "--include=dev", "--no-audit", "--no-fund"],
        cwd=output_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    ) as process:
        # Forward child output through Python so the console log also receives it.
        def forward_output():
            """Forward npm output through Python so both the terminal and compiler.log receive it."""
            for line in process.stdout:
                print(line, end="", flush=True)

        reader = Thread(target=forward_output, daemon=True)
        reader.start()
        try:
            process.wait(timeout=600)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.wait()
            raise RuntimeError("npm install timed out after 600 seconds") from error
        finally:
            reader.join()
        if process.returncode:
            raise RuntimeError(f"npm install failed with exit code {process.returncode}; see the npm output above")
