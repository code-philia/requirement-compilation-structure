"""Resolve the compiler input and output directories."""

import argparse
from pathlib import Path


def resolve_directories(args: argparse.Namespace) -> tuple[Path, Path]:
    """Resolve CLI paths and reject an output directory equal to or nested inside the source input directory."""
    input_dir = args.input.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()
    if output_dir == input_dir or input_dir in output_dir.parents:
        raise ValueError("Output directory must not equal or be inside the input directory")
    return input_dir, output_dir
