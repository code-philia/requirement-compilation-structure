"""Compile a requirement directory into an executable application."""

import argparse
from pathlib import Path
import sys

from infrastructure.compiler import Compiler
from infrastructure.utils.cli import resolve_directories
from infrastructure.utils.presentation.logging import configure_console


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Read public options and validate paths and the backend port before compilation."""
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("requirement_path", type=Path,
        help="Requirement directory containing requirements.yaml and reference assets")
    parser.add_argument("-o", "--output-dir", type=Path, required=True,
        help="Directory for the generated application and .arc artifacts")
    parser.add_argument("--model-log", "--debug-model-io", dest="model_log", action="store_true",
        help="Show detailed model I/O and save per-call prompt/response logs; usage and timing are always shown")
    parser.add_argument("--port", type=int, default=3000,
        help="Default generated backend port and frontend API proxy target (default: 3000)")
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError("--port must be between 1 and 65535")
        args.requirement_path, args.output_dir = resolve_directories(
            argparse.Namespace(input=args.requirement_path, output=args.output_dir))
        if not args.requirement_path.is_dir():
            raise ValueError(f"Input directory does not exist: {args.requirement_path}")
        if not (args.requirement_path / "requirements.yaml").is_file():
            raise ValueError(f"Missing requirement document: {args.requirement_path / 'requirements.yaml'}")
        if args.output_dir.exists() and not args.output_dir.is_dir():
            raise ValueError(f"Output must be a directory: {args.output_dir}")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return args


def main(argv: list[str] | None = None) -> None:
    configure_console()
    args = parse_args(argv)
    compiler = Compiler(args.requirement_path, args.output_dir, model_log=args.model_log, port=args.port)
    try:
        compiler.compile()
    except KeyboardInterrupt:
        print(f"Compilation interrupted at {compiler.current_stage or 'startup'}.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"Compilation failed at {compiler.current_stage or 'startup'}: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
