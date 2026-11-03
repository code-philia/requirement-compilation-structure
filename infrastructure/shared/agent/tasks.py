"""Isolate failed design tasks while preserving successful neighboring artifacts."""

from contextlib import contextmanager
from infrastructure.utils.presentation.events import task_scope


class StageIncomplete(RuntimeError):
    def __init__(self, stage, failures):
        self.failures = failures
        super().__init__(f'{stage}: {len(failures)} task(s) failed; all tasks were attempted. '
            'Continue with available artifacts.')


class TaskFailures:
    """Track failures in memory without writing per-task status files."""

    def __init__(self, arc_dir, stage, console):
        self.stage, self.console = stage, console
        self.report = {'status': 'RUNNING', 'tasks': {}}

    @contextmanager
    def task(self, identity):
        try:
            with task_scope(identity):
                yield
        except Exception as error:
            if isinstance(error, OSError):
                raise
            self.report['tasks'][identity] = {'status': 'FAILED', 'error': str(error),
                'error_type': type(error).__name__}
            self.console.show(self.stage + ' / ' + identity + ' | FAILED; continuing', str(error))
        else:
            self.report['tasks'][identity] = {'status': 'GREEN'}

    def finish(self):
        failures = [{'task': identity, **entry} for identity, entry in self.report['tasks'].items()
            if entry['status'] == 'FAILED']
        self.report['status'] = 'COMPLETED_WITH_FAILURES' if failures else 'GREEN'
        if failures:
            raise StageIncomplete(self.stage, failures)
