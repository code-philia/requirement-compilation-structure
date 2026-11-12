"""Run all compilation passes or one selected pass in the same pipeline."""

from pathlib import Path
import traceback

from infrastructure.pipeline.project_initialization import project_initialization
from infrastructure.pipeline.requirements import explore_requirement
from infrastructure.pipeline.database_design import build_er_schema, refine_database
from infrastructure.pipeline.database import implement_db
from infrastructure.pipeline.backend_apis import design_backend_joint
from infrastructure.pipeline.backend_implementation import implement_backend_tdd
from infrastructure.pipeline.frontend_joint import design_frontend_joint, implement_frontend_joint
from infrastructure.utils.presentation.console import show_panel
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.files import save_json
from infrastructure.shared.project.git import checkpoint, rollback_before_stage
from infrastructure.utils.presentation.events import begin_run, finish_run, begin_stage, finish_stage, timestamp


PIPELINE = (
    ("00_project_initialization", project_initialization, "project_files"),
    ("01_explore_requirement", explore_requirement, "requirements"),
    ("02_build_db_schema", build_er_schema, "db_schema"),
    ("03_infer_db_obligations", refine_database, "db_obligations"),
    ("04_implement_db", implement_db, "db_implementations"),
    ("05_design_backend_joint", design_backend_joint, "backend_plan"),
    ("06_implement_backend_tdd", implement_backend_tdd, "backend_checks"),
    ("07_design_frontend_joint", design_frontend_joint, "frontend_plan"),
    ("10_implement_frontend_joint", implement_frontend_joint, "frontend_e2e"),
)
STAGE_MAP = {name: (name, function, artifact) for name, function, artifact in PIPELINE}


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
        """Run a pass and preserve diagnostics for dependency-aware continuation."""
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
            if getattr(error, 'usable_artifacts', None):
                result['usable_artifacts'] = error.usable_artifacts
            if getattr(error, "failures", None):
                result.update(status="COMPLETED_WITH_FAILURES", failures=error.failures)
            show_panel("[FAILED] " + stage,
                result["error"] + "\nAccepted artifacts remain available. Other passes with usable prerequisites will continue.", tone="error")
        except BaseException:
            finish_stage(stage_event, "FAILED")
            raise
        status = result.get("status", "GREEN") if isinstance(result, dict) else "GREEN"
        self.report["stages"][stage] = {"status": status, **finish_stage(stage_event, status)}
        if isinstance(result, dict):
            for key in ("failures", "verification", "error", "error_type", "traceback", "diagnostics", "usable_artifacts"):
                if key in result:
                    self.report["stages"][stage][key] = result[key]
        save_json(self.arc_dir / "compilation.json", self.report)
        checkpoint(self.output_dir, stage=stage, task="stage report", action="Publish pass result",
            status=status, details=self.report["stages"][stage])
        return result

    def _missing_prerequisites(self, stage):
        required = {
            "01_explore_requirement": ["backend/package.json", "frontend/package.json"],
            "02_build_db_schema": [".arc/requirements.json"],
            "03_infer_db_obligations": [".arc/db_schema.json"],
            "04_implement_db": [".arc/db_schema.json", ".arc/db_obligations.json", "backend/package.json"],
            "05_design_backend_joint": [".arc/requirements.json", ".arc/db_schema.json", ".arc/db_obligations.json"],
            "06_implement_backend_tdd": [".arc/backend_plan.json", ".arc/db_schema.json", ".arc/backend_foundation.json"],
            "07_design_frontend_joint": [".arc/requirements.json", ".arc/db_schema.json", ".arc/backend_foundation.json"],
            "10_implement_frontend_joint": [".arc/frontend_plan.json", ".arc/db_schema.json", ".arc/backend_foundation.json"],
        }
        missing = [path for path in required.get(stage, []) if not (self.output_dir / path).is_file()]
        # Do not use stale deployment/DDL artifacts after a failed current import.
        gates = {
            "01_explore_requirement": ["00_project_initialization"],
            "03_infer_db_obligations": ["02_build_db_schema"],
            "04_implement_db": ["03_infer_db_obligations"],
            "05_design_backend_joint": ["03_infer_db_obligations", "04_implement_db"],
            "06_implement_backend_tdd": ["05_design_backend_joint", "03_infer_db_obligations", "04_implement_db"],
            "07_design_frontend_joint": ["05_design_backend_joint", "03_infer_db_obligations"],
            "10_implement_frontend_joint": ["05_design_backend_joint", "03_infer_db_obligations", "04_implement_db"],
        }
        input_pass = self.report['stages'].get('01_explore_requirement', {})
        if stage not in {'00_project_initialization', '01_explore_requirement'} and input_pass.get('status') in {'FAILED', 'BLOCKED'}:
            if not input_pass.get('usable_artifacts', {}).get('requirements'):
                missing.append('current requirement import did not complete')
        for owner in gates.get(stage, []):
            result = self.report['stages'].get(owner, {})
            if result.get('status') in {'FAILED', 'COMPLETED_WITH_FAILURES', 'BLOCKED'}:
                missing.append('prerequisite stage ' + owner + ' needs repair')
        return missing

    def _blocked(self, stage, missing):
        event = begin_stage(stage)
        result = {'status': 'BLOCKED', 'error': 'Required executable inputs are unavailable',
            'missing_prerequisites': missing, **finish_stage(event, 'BLOCKED')}
        self.report['stages'][stage] = result
        save_json(self.arc_dir / 'compilation.json', self.report)
        show_panel('[BLOCKED] ' + stage, '\n'.join(missing) + '\nContinuing independent planning/tasks.', tone='waiting')
        return result

    def compile(self, stage: str | None = None, *, from_stage: str | None = None) -> Path:
        """Run selected passes after restoring their previous successful checkpoint."""
        passes = PIPELINE
        if stage is not None and from_stage is not None:
            raise ValueError("stage and from_stage are mutually exclusive")
        selected = stage if stage is not None else from_stage
        restored = None
        if selected is not None:
            if selected not in STAGE_MAP:
                raise ValueError(f"Unknown stage: {selected}")
            names = [name for name, _, _ in PIPELINE]
            index = names.index(selected)
            if index > 0:
                restored = rollback_before_stage(self.output_dir, names[index - 1])
            passes = (STAGE_MAP[selected],) if stage is not None else PIPELINE[index:]
        self.artifacts.clear()
        self.report = {"status": "RUNNING", "stages": {}}
        show_panel("Requirement compiler | Pipeline",
            f"Input: {self.input_dir}\nOutput: {self.output_dir}\nPasses: {len(passes)}\nDetailed model logs: {'enabled' if self.model_log else 'disabled'}")
        run_token, run_id = begin_run(self.output_dir, self.input_dir, selected)
        self.report["selection"] = {"stage": stage, "from_stage": from_stage, "restored": restored}
        self.report.update(run_id=run_id, started_at=timestamp())
        try:
            for name, function, artifact in passes:
                missing = self._missing_prerequisites(name)
                if missing:
                    self.artifacts[artifact] = self._blocked(name, missing)
                    continue
                if function is project_initialization:
                    result = self._run(name, function, self.input_dir, self.output_dir, port=self.port, pause=self.pause)
                elif function in (build_er_schema, refine_database):
                    result = self._run(name, function, self.input_dir, self.arc_dir, pause=self.pause)
                elif function in (explore_requirement, design_frontend_joint, implement_frontend_joint):
                    result = self._run(name, function, self.input_dir, self.arc_dir, pause=self.pause)
                else:
                    result = self._run(name, function, self.arc_dir, pause=self.pause)
                self.artifacts[artifact] = result
                # One bounded recovery sweep after neighboring requirements have
                # produced new shared owners. Accepted requirements are reused by
                # the existing content/dependency checkpoints, not regenerated.
                # Design requirements map to API/page ID lists, not status records.
                # Inspect requirement outcomes only for implementation reports.
                if function not in (implement_backend_tdd, implement_frontend_joint):
                    continue
                entries = result.get('requirements', {}) if isinstance(result, dict) else {}
                outcomes = [entry for entry in entries.values() if isinstance(entry, dict)] if isinstance(entries, dict) else []
                failed = any(entry.get('status') == 'FAILED' for entry in outcomes)
                progressed = any(entry.get('status') == 'GREEN' for entry in outcomes)
                if failed and progressed:
                    previous = dict(self.report['stages'][name])
                    show_panel('Incremental recovery | ' + name,
                        'Retry unresolved requirements once using new shared implementations and saved failure feedback. Accepted checkpoints are reused.')
                    if function is implement_backend_tdd:
                        result = self._run(name, function, self.arc_dir, pause=self.pause)
                    else:
                        result = self._run(name, function, self.input_dir, self.arc_dir, pause=self.pause)
                    self.artifacts[artifact] = result
                    self.report['stages'][name]['recovery_attempts'] = [previous]
                    save_json(self.arc_dir / 'compilation.json', self.report)
            self.current_stage = None
            incomplete = [name for name, result in self.report["stages"].items()
                if result["status"] in {"FAILED", "COMPLETED_WITH_FAILURES", "BLOCKED"}]
            self.report['attempted_all_stages'] = len(self.report['stages']) == len(passes)
            queue = [{'stage': name, 'status': self.report['stages'][name]['status'],
                'error': self.report['stages'][name].get('error'),
                'missing_prerequisites': self.report['stages'][name].get('missing_prerequisites', []),
                'failures': self.report['stages'][name].get('failures', []),
                'verification': self.report['stages'][name].get('verification', {}),
                'resume': '--stage ' + name} for name in incomplete]
            save_json(self.arc_dir / 'repair_queue.json', {'pending': queue,
                'instruction': 'Repair prerequisites before blocked stages; reuse accepted requirement checkpoints. Never waive source acceptance.'})
            self.report['repair_queue'] = '.arc/repair_queue.json'
            self.report["status"] = "COMPLETED_WITH_FAILURES" if incomplete else "GREEN"
            save_json(self.arc_dir / "compilation.json", self.report)
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
            # Commit only after all final metadata is written, on every exit path.
            # Otherwise finished_at/duration leave a dirty report that blocks the
            # next stage's checkpoint restore.
            incomplete = [name for name, result in self.report["stages"].items()
                if result["status"] in {"FAILED", "COMPLETED_WITH_FAILURES", "BLOCKED", "INTERRUPTED"}]
            checkpoint(self.output_dir, stage="compiler", task="pipeline", action="Publish final compilation report",
                status=self.report["status"], details={"stages": self.report["stages"], "incomplete_stages": incomplete,
                    "finished_at": self.report.get("finished_at")})
