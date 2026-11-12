"""Reuse successful browser/type checks only for identical executable inputs."""

import hashlib

from infrastructure.shared.agent.files import source_paths


class FrontendCheckCache:
    def __init__(self, output, checks):
        self.output, self.checks = output, checks
        self.results = {}
        self.stats = {'executed':0,'reused':0}

    def fingerprint(self):
        paths = {path for root in ('frontend','backend') for path in source_paths(self.output,root)
            if not set(path.split('/')) & {'test-results','playwright-report','artifacts'}}
        paths.discard('backend/src/api/endpoints.json')
        paths.update({'package.json','package-lock.json','npm-shrinkwrap.json'})
        digest = hashlib.sha256()
        for relative in sorted(paths):
            path = self.output/relative
            if path.is_file() and not path.is_symlink():
                digest.update(relative.encode()+b'\0'+hashlib.sha256(path.read_bytes()).digest())
        return digest.hexdigest()

    def run(self, kind, files=None, **options):
        selected = None if files is None else tuple(sorted(set(files)))
        state = self.fingerprint()
        key = (kind,selected,tuple(sorted(options.items())),state)
        if key in self.results:
            self.stats['reused'] += 1
            return {**self.results[key],'reused_unchanged_sources':True}
        self.stats['executed'] += 1
        action = getattr(self.checks,kind)
        result = action(**options) if selected is None else action(list(selected),**options)
        if (result.get('returncode')==0 and not any(result.get(k) for k in ('failed','skipped','flaky','errors'))
                and (kind!='tests' or result.get('passed',0)>0) and self.fingerprint()==state):
            self.results[key] = dict(result)
        return result

    def typecheck(self, files, full_source=True):
        return self.run('typecheck',files,full_source=full_source)

    def tests(self, files):
        return self.run('tests',files)

    def build(self):
        return self.run('build')
