"""Keep real failure evidence without carrying successful regression output."""


class CheckFailure(ValueError):
    def __init__(self, message, report):
        self.feedback = report
        super().__init__(message + ': ' + str(report))


def compact_feedback(item):
    if isinstance(item, dict):
        if item.get('returncode') == 0:
            return {'returncode': 0}
        return {key: compact_feedback(child) for key, child in item.items()
            if not (key in {'output', 'stdout', 'files'} and item.get('failures'))}
    if isinstance(item, list):
        kept = [compact_feedback(child) for child in item[:8]]
        if len(item) > 8:
            kept.append({'additional_entries_in_full_log': len(item) - 8})
        return kept
    if isinstance(item, str) and len(item) > 6000:
        return item[:5000] + '\n[Middle omitted; full evidence remains in logs]\n' + item[-1000:]
    return item


def failure_signature(report):
    """Ignore timing/UUID noise, retaining actual failing assertions and errors."""
    import hashlib
    import json
    import re
    def select(value):
        if isinstance(value, dict):
            if value.get('returncode') == 0:
                return None
            failures = value.get('failures') or value.get('errors')
            if failures:
                return select(failures)
            return {k: select(v) for k, v in value.items() if k not in {
                'elapsed_seconds', 'duration_ms', 'seconds', 'passed', 'pass', 'cases',
                'previous_diagnosis', 'stdout', 'stderr', 'test_seconds'}}
        if isinstance(value, list):
            return [select(v) for v in value]
        if isinstance(value, str):
            value = re.sub(r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b', '<uuid>', value, flags=re.I)
            value = re.sub(r'\.tsconfig-[\w.-]+\.json', '<tsconfig>', value)
            return re.sub(r'duration_ms:\s*[\d.]+', 'duration_ms:<time>', value)
        return value
    return hashlib.sha256(json.dumps(select(report), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class TestSetupRequired(CheckFailure):
    """Fixture setup failed before the feature action; implementation must not seed production."""
