"""Command-line entry point for the requirement compiler."""

import argparse
from pathlib import Path

from compiler import Compiler
from infrastructure.utils.presentation.logging import configure_console


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile requirements into a complete web application")
    parser.add_argument("requirement_path", type=Path, help="Input directory containing requirements.yaml and referenced images")
    parser.add_argument("-o", "--output-dir", "--ouput-dir", dest="output_dir", required=True, type=Path,
                        help="Generated application and compilation artifact directory")
    parser.add_argument("--port", type=int, default=3000, help="Default backend port injected into newly initialized templates (default: 3000)")
    return parser


def main(argv: list[str] | None = None) -> None:
    configure_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    compiler = None
    try:
        compiler = Compiler(args.requirement_path, args.output_dir, args.port)
        compiler.compile()
    except KeyboardInterrupt:
        parser.exit(130, "Compilation interrupted.\n")
    except Exception as error:
        stage = f" at {compiler.current_stage}" if compiler and compiler.current_stage else ""
        parser.exit(1, f"Compilation failed{stage}: {error}\n")


if __name__ == "__main__":
    main()
