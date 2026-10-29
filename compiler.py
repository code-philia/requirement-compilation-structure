"""Compile requirements by calling reusable stage behaviors directly."""

from pathlib import Path
from time import monotonic

from infrastructure.shared.project.workflow import project_initialization
from infrastructure.stages.requirements.exploration import explore_requirement
from infrastructure.stages.database.schema_synthesis import build_db_schema
from infrastructure.stages.database.obligations.inference import infer_db_obligations
from infrastructure.stages.database.obligations.review import check_db_obligations
from infrastructure.stages.database.implementation import implement_db
from infrastructure.stages.backend.decomposition import decompose_backend_apis
from infrastructure.stages.backend.contract_inference import infer_api_contracts
from infrastructure.stages.backend.implementation import implement_backend_tdd
from infrastructure.stages.frontend.ui.design_stage import design_frontend_ui
from infrastructure.stages.frontend.ui.implementation_stage import implement_frontend_ui
from infrastructure.stages.frontend.interactions.design_stage import design_ui_interactions
from infrastructure.stages.frontend.interactions.implementation_stage import implement_frontend_interactions
from infrastructure.utils.presentation.console import show_panel
from infrastructure.utils.presentation.logging import console_log, stage_scope
from infrastructure.utils.presentation.stages import stage_label


class Compiler:
    """Own the source document, application workspace, port and sequential pipeline."""

    def __init__(self, requirement_path: str | Path, output_dir: str | Path, port: int = 3000) -> None:
        self.requirement_path = Path(requirement_path).expanduser().resolve()
        if self.requirement_path.is_dir():
            self.requirement_path = self.requirement_path / "requirements.yaml"
        self.input_dir = self.requirement_path.parent
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.arc_dir = self.output_dir / ".arc"
        self.port = port
        self.current_stage: str | None = None
        self.completed_stages: list[str] = []
        if not self.requirement_path.is_file():
            raise ValueError(f"Requirement document does not exist: {self.requirement_path}")
        if self.output_dir == self.input_dir or self.input_dir in self.output_dir.parents:
            raise ValueError("Output directory must not equal or be inside the input directory")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("Port must be an integer between 1 and 65535")

    def compile(self) -> Path:
        """Run all stages with one log session and return the generated application directory."""
        started = monotonic()
        with console_log(self.output_dir):
            show_panel("Requirement compiler | Pipeline",
                f"Requirements: {self.requirement_path}\nOutput: {self.output_dir}\nDefault backend port: {self.port}")
            self.pipeline()
            show_panel("[DONE] Compilation completed",
                f"Output: {self.output_dir}\nCompleted {len(self.completed_stages)} stages in {monotonic() - started:.1f}s",
                tone="success")
        return self.output_dir

    def _run_stage(self, number: str, behavior, *args, **kwargs) -> None:
        """Stop on failure and retain the stage identity for the CLI error message."""
        self.current_stage = stage_label(number)
        with stage_scope(self.current_stage):
            show_panel(self.current_stage, "Running stage behavior")
            behavior(*args, **kwargs)
        self.completed_stages.append(number)

    def pipeline(self) -> None:
        """Execute the current 00–12 flow without importing or launching numbered scripts."""
        # Stage 00: initialize the application template and its default backend port.
        self._run_stage("00", project_initialization, self.output_dir, port=self.port)

        # Stage 01: parse the selected requirement document and analyze its reference images.
        self._run_stage("01", explore_requirement, self.input_dir, self.arc_dir,
                        requirement_path=self.requirement_path)

        # Stage 02: synthesize the shared database schema.
        self._run_stage("02", build_db_schema, self.arc_dir)

        # Stage 03: infer and enforce database read/write obligations.
        self._run_stage("03", infer_db_obligations, self.arc_dir)

        # Stage 04: validate and display the database obligation records.
        self._run_stage("04", check_db_obligations, self.arc_dir)

        # Stage 05: implement the database schema as validated SQLite table definitions.
        self._run_stage("05", implement_db, self.arc_dir)

        # Stage 06: decompose backend APIs and allocate their dataflow obligations.
        self._run_stage("06", decompose_backend_apis, self.arc_dir)

        # Stage 07: infer preconditions and postconditions over the fixed API interfaces.
        self._run_stage("07", infer_api_contracts, self.arc_dir)

        # Stage 08: generate backend tests, confirm RED, and implement APIs until GREEN.
        self._run_stage("08", implement_backend_tdd, self.arc_dir)

        # Stage 09: design UI elements and frontend data using the accepted backend contracts.
        self._run_stage("09", design_frontend_ui, self.input_dir, self.arc_dir)

        # Stage 10: implement the saved UI design through existence-test TDD.
        self._run_stage("10", implement_frontend_ui, self.input_dir, self.arc_dir)

        # Stage 11: design frontend interactions, API calls and event contracts.
        self._run_stage("11", design_ui_interactions, self.input_dir, self.arc_dir)

        # Stage 12: implement interactions and validate the application with end-to-end TDD.
        self._run_stage("12", implement_frontend_interactions, self.input_dir, self.arc_dir)
