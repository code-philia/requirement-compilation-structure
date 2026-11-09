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
