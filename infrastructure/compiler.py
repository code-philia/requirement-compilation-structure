"""Run all compilation passes or one selected pass in the same pipeline."""

from pathlib import Path
import traceback

from infrastructure.pipeline.project_initialization import project_initialization
from infrastructure.pipeline.requirements import explore_requirement
from infrastructure.pipeline.db_schema import build_db_schema
from infrastructure.pipeline.db_obligations import infer_db_obligations
from infrastructure.pipeline.database import implement_db
from infrastructure.pipeline.backend_apis import design_backend_apis
from infrastructure.pipeline.backend_implementation import implement_backend_tdd
from infrastructure.pipeline.ui_design import design_frontend_ui
from infrastructure.pipeline.ui_implementation import implement_frontend_ui
from infrastructure.pipeline.frontend_triggers import design_frontend_triggers
from infrastructure.pipeline.frontend_implementation import implement_frontend_triggers
from infrastructure.utils.presentation.console import show_panel
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.files import save_json
from infrastructure.shared.project.git import checkpoint, rollback_before_stage
from infrastructure.utils.presentation.events import begin_run, finish_run, begin_stage, finish_stage, timestamp


PIPELINE = (
    ("00_project_initialization", project_initialization, "project_files"),
    ("01_explore_requirement", explore_requirement, "requirements"),
    ("02_build_db_schema", build_db_schema, "db_schema"),
    ("03_infer_db_obligations", infer_db_obligations, "db_obligations"),
    ("04_implement_db", implement_db, "db_implementations"),
    ("05_design_backend_apis", design_backend_apis, "backend_apis"),
    ("06_implement_backend_tdd", implement_backend_tdd, "backend_checks"),
    ("07_design_ui", design_frontend_ui, "ui_design"),
    ("08_implement_ui", implement_frontend_ui, "ui_checks"),
    ("09_design_frontend_triggers", design_frontend_triggers, "frontend_triggers"),
    ("10_implement_frontend_tdd", implement_frontend_triggers, "frontend_e2e"),
)

class Compiler:
    """Own shared paths, configuration, and results for one compilation."""

    def __init__(self, input_dir: Path, output_dir: Path, model_log: bool = False,
            port: int = 3000, pause: bool = False) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("Backend port must be between 1 and 65535")
        self.input_dir = Path(input_dir).expanduser().resolve()
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.arc_dir = self.output_dir / ".arc"
        self.model_log = model_log
        self.port = port
        self.pause = pause
        self.artifacts: dict[str, object] = {}
        self.current_stage: str | None = None
        self.report = {"status": "NOT_STARTED", "stages": {}}

    def _run(self, stage: str, function, *arguments, **options):
        """Attempt every pass; keep failures explicit without aborting later passes."""
        self.current_stage = stage
        stage_event = begin_stage(stage)
        self.report["stages"][stage] = {"status": "RUNNING", "started_at": timestamp()}
        save_json(self.arc_dir / "compilation.json", self.report)
        try:
            with console_log(self.output_dir, stage=stage,
                    model_log=self.model_log, debug_model_io=self.model_log):
                result = function(*arguments, **options)
        except KeyboardInterrupt as error:
            self.report["status"] = "INTERRUPTED"
            self.report["stages"][stage] = {"status": "INTERRUPTED", "error": str(error),
                **finish_stage(stage_event, "INTERRUPTED")}
            save_json(self.arc_dir / "compilation.json", self.report)
            checkpoint(self.output_dir, stage=stage, task="stage report", action="Record interrupted pass",
                status="INTERRUPTED", details=self.report["stages"][stage])
            raise
        except Exception as error:
            result = {"status": "FAILED", "error": str(error),
                "error_type": type(error).__name__, "traceback": traceback.format_exc()}
            if getattr(error, "failures", None):
                result.update(status="COMPLETED_WITH_FAILURES", failures=error.failures)
            show_panel("[FAILED; continuing] " + stage,
                result["error"] + "\nAccepted artifacts remain available. Attempt the next pass.", tone="error")
        except BaseException:
            finish_stage(stage_event, "FAILED")
            raise
        status = result.get("status", "GREEN") if isinstance(result, dict) else "GREEN"
        self.report["stages"][stage] = {"status": status, **finish_stage(stage_event, status)}
        if isinstance(result, dict):
            for key in ("failures", "verification", "error", "error_type", "traceback"):
                if key in result:
                    self.report["stages"][stage][key] = result[key]
        save_json(self.arc_dir / "compilation.json", self.report)
        checkpoint(self.output_dir, stage=stage, task="stage report", action="Publish pass result",
            status=status, details=self.report["stages"][stage])
        return result

    def compile(self, stage: str | None = None, *, from_stage: str | None = None) -> Path:
        """Run all passes, or restore the previous checkpoint before selected passes."""
        passes = PIPELINE
        if stage is not None and from_stage is not None:
            raise ValueError("stage and from_stage are mutually exclusive")
        selected = stage if stage is not None else from_stage
        if selected is not None:
            passes = ()
            for index, entry in enumerate(PIPELINE):
                if entry[0] == selected:
                    passes = (entry,) if stage is not None else PIPELINE[index:]
                    break
            if not passes:
                raise ValueError(f"Unknown stage: {selected}. Use a full stage name such as 06_implement_backend_tdd.")
        if selected is not None:
            names = [name for name, _, _ in PIPELINE]
            index = names.index(selected)
            if index > 0:
                rollback_before_stage(self.output_dir, names[index - 1])
        self.artifacts.clear()
        self.report = {"status": "RUNNING", "stages": {}}
        show_panel("Requirement compiler | Pipeline",
            f"Input: {self.input_dir}\nOutput: {self.output_dir}\nPasses: {len(passes)}\nDetailed model logs: {'enabled' if self.model_log else 'disabled'}")
        run_token, run_id = begin_run(self.output_dir, self.input_dir, selected)
        self.report["selection"] = {"stage": stage, "from_stage": from_stage}
        self.report.update(run_id=run_id, started_at=timestamp())
        try:
            # =========================================
            # main loop over all passes in the pipeline
            # =========================================
            for name, function, artifact in passes:
                if function is project_initialization:
                    result = self._run(name, function, self.input_dir, self.output_dir, port=self.port, pause=self.pause)
                elif function in (explore_requirement, design_frontend_ui, implement_frontend_ui,
                        design_frontend_triggers, implement_frontend_triggers):
                    result = self._run(name, function, self.input_dir, self.arc_dir, pause=self.pause)
                else:
                    result = self._run(name, function, self.arc_dir, pause=self.pause)
                self.artifacts[artifact] = result

            # ========================================
            #        final report and exit
            # ========================================
            self.current_stage = None
            incomplete = [name for name, result in self.report["stages"].items()
                if result["status"] in {"FAILED", "COMPLETED_WITH_FAILURES"}]
            self.report["status"] = "COMPLETED_WITH_FAILURES" if incomplete else "GREEN"
            show_panel("[DONE] Requirement compilation | " + self.report["status"],
                f"Application: {self.output_dir}\nReport: {self.arc_dir / 'compilation.json'}"
                + ("\nIncomplete stages: " + ", ".join(incomplete) if incomplete else ""),
                tone="error" if incomplete else "success")
            return self.output_dir
        except BaseException as error:
            self.report["status"] = "INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "FAILED"
            raise
        finally:
            self.report.update(finish_run(run_token, self.report["status"]))
            save_json(self.arc_dir / "compilation.json", self.report)
            incomplete = [name for name, result in self.report["stages"].items()
                if result["status"] in {"FAILED", "COMPLETED_WITH_FAILURES", "INTERRUPTED"}]
            checkpoint(self.output_dir, stage="compiler", task="pipeline", action="Publish final compilation report",
                status=self.report["status"], details={"stages": self.report["stages"], "incomplete_stages": incomplete})
