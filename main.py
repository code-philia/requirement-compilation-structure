"""Compile a requirement directory into an executable application."""

import argparse
from pathlib import Path
import sys

from infrastructure.compiler import Compiler
from infrastructure.utils.cli import COMPILER_DIR, resolve_directories
from infrastructure.utils.presentation.logging import configure_console


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Read the three public options and validate input/output locations before compilation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=COMPILER_DIR / "input",
        help="Requirement directory containing requirements.yaml and reference assets (default: compiler/input)")
    parser.add_argument("--output", "--output-dir", dest="output", type=Path, required=True,
        help="Directory for the generated application and .arc artifacts")
    parser.add_argument("--model-log", "--debug-model-io", dest="model_log", action="store_true",
        help="Show detailed model I/O and save per-call prompt/response logs; usage and timing are always shown")
    args = parser.parse_args(argv)
    try:
        args.input, args.output = resolve_directories(args)
        if not args.input.is_dir():
            raise ValueError(f"Input directory does not exist: {args.input}")
        if not (args.input / "requirements.yaml").is_file():
            raise ValueError(f"Missing requirement document: {args.input / 'requirements.yaml'}")
        if args.output.exists() and not args.output.is_dir():
            raise ValueError(f"Output must be a directory: {args.output}")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return args


def main(argv: list[str] | None = None) -> None:
    configure_console()
    args = parse_args(argv)
    compiler = Compiler(args.input, args.output, model_log=args.model_log)
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
