"""Zip the current Git working directory, respecting Git ignore rules except for .env.

Windows:       python scripts/package.py
Linux / macOS: python3 scripts/package.py
Custom name:   python scripts/package.py --output release.zip

Requires Git on PATH and a working tree containing the current directory.
Include .env files, .gitignore files, modified files, and non-ignored untracked files.
Exclude .git metadata and this invocation's output and temporary archive.
Nested repositories such as arc-bench use their own Git ignore rules.
Symbolic links are stored as links without traversing their targets.
"""

import argparse
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import zipfile


def ignored_names(directory: Path, paths: list[Path]) -> set[str]:
    """Ask Git to apply ignore rules, including to already tracked files."""
    names = b"\0".join(os.fsencode(path.name) for path in paths) + b"\0"
    result = subprocess.run(["git", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=directory, input=names, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode not in (0, 1):
        raise OSError(result.stderr.decode("utf-8", errors="replace").strip())
    return {os.fsdecode(name) for name in result.stdout.split(b"\0") if name}


def package_directory(root: Path, output: Path) -> int:
    """Archive non-ignored entries and .env, replacing the output only on success."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=f".{output.name}.", suffix=".tmp",
            dir=output.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)

    excluded = {output, temporary_path}
    entries = 0
    try:
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED,
                compresslevel=6, allowZip64=True, strict_timestamps=False) as archive:
            pending = [root]
            while pending:
                directory = pending.pop()
                paths = [path for path in sorted(directory.iterdir())
                    if path.name != ".git" and path not in excluded]
                if not paths:
                    continue
                ignored = ignored_names(directory, paths)
                for path in paths:
                    if path.name in ignored and path.name != ".env":
                        continue
                    relative = path.relative_to(root).as_posix()
                    if path.is_symlink():
                        entry = zipfile.ZipInfo(relative)
                        entry.create_system = 3
                        entry.external_attr = path.lstat().st_mode << 16
                        archive.writestr(entry, os.readlink(path))
                    elif path.is_dir():
                        archive.write(path, relative)
                        pending.append(path)
                    elif path.is_file():
                        archive.write(path, relative)
                    else:
                        kind = stat.S_IFMT(path.lstat().st_mode)
                        raise OSError(f"Cannot archive special file {path} (type {kind:#o})")
                    entries += 1
        os.replace(temporary_path, output)
    finally:
        temporary_path.unlink(missing_ok=True)
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-o", "--output", type=Path, default=Path("compiler.zip"),
        help="Output archive path (default: compiler.zip)")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    output = args.output.expanduser().resolve()
    print(f"Source: {root}")
    print(f"Archive: {output}")
    try:
        entries = package_directory(root, output)
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        parser.exit(1, f"Packaging failed: {error}\n")
    print(f"Created {output} ({entries} entries, {output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
