"""Run the complete requirement compiler in one process using the existing passes."""

from importlib import import_module
from pathlib import Path

from infrastructure.utils.presentation.console import show_panel
from infrastructure.utils.presentation.logging import console_log


class Compiler:
    """Own shared paths, configuration, and results for one compilation."""

    def __init__(self, input_dir: Path, output_dir: Path, model_log: bool = False, port: int = 3000) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("Backend port must be between 1 and 65535")
        self.input_dir = Path(input_dir).expanduser().resolve()
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.arc_dir = self.output_dir / ".arc"
        self.model_log = model_log
        self.port = port
        self.artifacts: dict[str, object] = {}
        self.current_stage: str | None = None

    def _run(self, module: str, function: str, *arguments, **options):
        """Call a pass directly, preserving its stage identity and error traceback."""
        self.current_stage = module + ".py"
        with console_log(self.output_dir, stage=self.current_stage,
                model_log=self.model_log, debug_model_io=self.model_log):
            return getattr(import_module(module), function)(*arguments, **options)

    def compile(self) -> Path:
        """Execute the 13 compilation passes in order and return the generated application directory."""
        self.artifacts.clear()
        show_panel("Requirement compiler | Pipeline",
            f"Input: {self.input_dir}\nOutput: {self.output_dir}\nPasses: 13\nDetailed model logs: {'enabled' if self.model_log else 'disabled'}")
        self.artifacts["project_files"] = self._run(
            "00_project_initialization", "project_initialization", self.output_dir, port=self.port)
        self.artifacts["requirements"] = self._run(
            "01_explore_requirement", "explore_requirement", self.input_dir, self.arc_dir)
        self.artifacts["db_schema"] = self._run(
            "02_build_db_schema", "build_db_schema", self.arc_dir)
        self.artifacts["db_obligations"] = self._run(
            "03_infer_db_obligations", "infer_db_obligations", self.arc_dir)
        self.artifacts["db_obligations"] = self._run(
            "04_check_db_obligations", "check_db_obligations", self.arc_dir)
        self.artifacts["db_implementations"] = self._run(
            "05_implement_db", "implement_db", self.arc_dir)
        self.artifacts["backend_apis"] = self._run(
            "06_design_backend_apis", "design_backend_apis", self.arc_dir)
        self.artifacts["backend_apis"] = self._run(
            "07_check_backend_apis", "check_backend_apis", self.arc_dir)
        self.artifacts["backend_checks"] = self._run(
            "08_implement_backend_tdd", "implement_backend_tdd", self.arc_dir)
        self.artifacts["ui_design"] = self._run(
            "09_design_ui", "design_frontend_ui", self.input_dir, self.arc_dir)
        self.artifacts["ui_checks"] = self._run(
            "10_implement_ui", "implement_frontend_ui", self.input_dir, self.arc_dir)
        self.artifacts["frontend_triggers"] = self._run(
            "11_design_frontend_triggers", "design_frontend_triggers", self.input_dir, self.arc_dir)
        self.artifacts["frontend_e2e"] = self._run(
            "12_implement_frontend_tdd", "implement_frontend_triggers", self.input_dir, self.arc_dir)
        self.current_stage = None
        show_panel("[DONE] Requirement compilation completed", f"Application: {self.output_dir}", tone="success")
        return self.output_dir
