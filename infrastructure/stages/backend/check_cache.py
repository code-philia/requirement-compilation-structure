"""Reuse successful checks only while all backend sources and inputs remain identical."""

import hashlib
from pathlib import Path

from infrastructure.shared.agent.files import source_paths


class BackendCheckCache:
    """In-memory per-run cache; failed checks and prior runs are never reused."""

    def __init__(self, output, checks):
        self.output, self.checks = Path(output), checks
        self.results = {}
        self.stats = {'executed': 0, 'reused': 0}

    def fingerprint(self):
        digest = hashlib.sha256()
        paths = set(source_paths(self.output, 'backend'))
        # Compiler-owned frontend handoff, never executable backend input. Publishing
        # accepted documentation must not invalidate identical cumulative checks.
        paths.discard('backend/src/api/endpoints.json')
        paths.update({'package.json', 'package-lock.json', 'npm-shrinkwrap.json'})
        for relative in sorted(paths):
            path = self.output / relative
            if path.is_file() and not path.is_symlink():
                data = path.read_bytes()
                digest.update(relative.encode())
                digest.update(b'\0')
                digest.update(hashlib.sha256(data).digest())
        return digest.hexdigest()

    def run(self, kind, files=None):
        selected = None if files is None else tuple(sorted(set(files)))
        key = (kind, selected, self.fingerprint())
        if key in self.results:
            self.stats['reused'] += 1
            return {**self.results[key], 'reused_unchanged_sources': True}
        self.stats['executed'] += 1
        result = getattr(self.checks, kind)(None if selected is None else list(selected))
        # Capture before execution; the check must not mutate its own source inputs.
        if (result.get('returncode') == 0 and (kind != 'tests' or result.get('pass', 0) > 0)
                and not any(result.get(k) for k in ('fail', 'skipped', 'todo'))):
            if key[2] == self.fingerprint():
                self.results[key] = dict(result)
        return result
