"""Step 01: read the requirement tree, display every field, and analyze images. CLI wrapper."""

from contextlib import ExitStack

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log
import yaml
from infrastructure.stages.requirements.exploration import explore_requirement, RequirementExplorer, load_requirements


def main() -> None:
    parser = create_parser("Step 01: Explore Requirement Tree")
    parser.add_argument(
        "--browse", action="store_true",
        help="Skip analysis and browse requirements interactively",
    )
    parser.add_argument(
        "--no-browse", action="store_true",
        help="Run analysis only (used by non-interactive pipelines)",
    )
    args = parser.parse_args()

    if args.browse and args.no_browse:
        parser.error("--browse and --no-browse cannot be used together")

    input_dir = args.input.expanduser().resolve()
    source = input_dir / "requirements.yaml"
    if args.browse:
        try:
            if not input_dir.is_dir():
                raise ValueError(f"Input directory does not exist or is not a directory: {input_dir}")
            root = load_requirements(source)
            RequirementExplorer(source, root).run()
        except (OSError, ValueError, yaml.YAMLError) as error:
            parser.exit(1, f"Cannot browse requirements: {error}\n")
        return

    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir))
            if not input_dir.is_dir():
                raise ValueError(f"Input directory does not exist or is not a directory: {input_dir}")
            requirements = explore_requirement(input_dir, output_dir / ".arc", args.pause)
            if not args.no_browse:
                RequirementExplorer(source, requirements).run()
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
