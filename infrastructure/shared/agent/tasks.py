"""Isolate failed design tasks while preserving successful neighboring artifacts."""

from contextlib import contextmanager
import traceback

from infrastructure.utils.files import save_json


class StageIncomplete(RuntimeError):
    def __init__(self, stage, failures):
        self.failures = failures
        super().__init__(f'{stage}: {len(failures)} task(s) failed; all tasks were attempted. '
            'See .arc/stage_tasks for details. Continue with available artifacts.')


class TaskFailures:
    """Keep per-task failures out of canonical schema/API/UI data formats."""

    def __init__(self, arc_dir, stage, console):
        self.path = arc_dir / 'stage_tasks' / (stage + '.json')
        self.stage, self.console = stage, console
        self.report = {'status': 'RUNNING', 'tasks': {}}
        save_json(self.path, self.report)

    @contextmanager
    def task(self, identity):
        try:
            yield
        except Exception as error:
            if isinstance(error, OSError):
                raise
            self.report['tasks'][identity] = {'status': 'FAILED', 'error': str(error),
                'error_type': type(error).__name__, 'traceback': traceback.format_exc()}
            self.console.show(self.stage + ' / ' + identity + ' | FAILED; continuing', str(error))
        else:
            self.report['tasks'][identity] = {'status': 'GREEN'}
        finally:
            save_json(self.path, self.report)

    def finish(self):
        failures = [{'task': identity, **entry} for identity, entry in self.report['tasks'].items()
            if entry['status'] == 'FAILED']
        self.report['status'] = 'COMPLETED_WITH_FAILURES' if failures else 'GREEN'
        save_json(self.path, self.report)
        if failures:
            raise StageIncomplete(self.stage, failures)
