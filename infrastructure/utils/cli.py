"""Consistent source, output, and pause options across all step scripts."""

import argparse
from pathlib import Path


COMPILER_DIR = Path(__file__).resolve().parents[2]


def create_parser(description: str) -> argparse.ArgumentParser:
    """Create the common input, output, and optional teaching-pause arguments used by numbered entry scripts."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--input", type=Path, default=COMPILER_DIR / "input",
        help="Source requirement/image directory (used by steps 01/09/10/11/12; default: compiler/input)",
    )
    parser.add_argument(
        "--output", type=Path, default=COMPILER_DIR / "output",
        help="Target directory containing shared .arc artifacts (default: compiler/output)",
    )
    parser.add_argument("--pause", action="store_true", help="Wait for Enter after each display stage")
    return parser


def resolve_directories(args: argparse.Namespace) -> tuple[Path, Path]:
    """Resolve CLI paths and reject an output directory equal to or nested inside the source input directory."""
    input_dir = args.input.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()
    if output_dir == input_dir or input_dir in output_dir.parents:
        raise ValueError("Output directory must not equal or be inside the input directory")
    return input_dir, output_dir
