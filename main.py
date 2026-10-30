"""ARC-Bench entry point skeleton: parse arguments without running a workflow."""

import argparse
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "requirement_path",
        type=Path,
        help="Requirement directory containing requirements.yaml and reference assets",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output application directory supplied by the Runner",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()


if __name__ == "__main__":
    main()
