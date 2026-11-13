"""Import immutable requirement tests, binding filenames to exact requirement IDs."""

import hashlib
import json
from pathlib import Path

from infrastructure.utils.files import save_bytes, save_json
from infrastructure.utils.files import save_text
from infrastructure.stages.frontend.triggers.testing import E2EChecks


ROOT = 'frontend/tests/e2e/source'
SUFFIXES = ('.spec.ts','.test.ts','.spec.tsx','.test.tsx','.spec.js','.test.js','.spec.mjs','.test.mjs')
EXCLUDED = {'node_modules','.git','test-results','playwright-report','__pycache__'}


class SourceTests:
    def __init__(self, input_dir, output, requirements):
        self.output, self.source = Path(output).resolve(), Path(input_dir)/'tests'
        self.bindings = {rid:[] for rid in requirements}
        self.files, self.unmatched = {}, []
        self.specs = []
        if self.source.is_dir():
            for path in sorted(self.source.rglob('*')):
                parts = path.relative_to(self.source).parts
                if any(part in EXCLUDED or part.startswith('.') for part in parts) or path.name=='results.json':
                    continue
                if path.is_symlink():
                    raise ValueError('Source test bundle must use regular files: '+path.relative_to(self.source).as_posix())
                if not path.is_file():
                    continue
                relative = path.relative_to(self.source).as_posix()
                self.files[ROOT+'/'+relative] = hashlib.sha256(path.read_bytes()).hexdigest()
                suffix = next((suffix for suffix in SUFFIXES if path.name.endswith(suffix)),None)
                if suffix:
                    rid = path.name[:-len(suffix)]
                    target = ROOT+'/'+relative
                    self.specs.append(target)
                    if rid in self.bindings:
                        self.bindings[rid].append(target)
                    else:
                        self.unmatched.append({'id':rid,'test_path':target})
        self.manifest = {'mode':'supplied_source_tests','root':ROOT,'files':self.files,
            'requirements':self.bindings,
            'unmatched_tests':self.unmatched,'binding_policy':'Exact filename stem equals requirement ID; no semantic guessing.'}

    def publish(self, arc_dir):
        # Replace only compiler-owned copies from the previous import, leaving the
        # source bundle and all other test directories untouched.
        previous = arc_dir/'frontend_source_tests.json'
        if previous.is_file():
            try:
                old = json.loads(previous.read_text())
            except ValueError:
                old = {}
            for relative in old.get('files',{}):
                path = self.output/relative
                if relative not in self.files and path.resolve().is_relative_to((self.output/ROOT).resolve()) and path.is_file():
                    path.unlink()
        for relative in self.files:
            source = self.source/Path(relative).relative_to(ROOT)
            target = self.output/relative
            if not target.resolve().is_relative_to(self.output) or any(parent.is_symlink() for parent in [target,*target.parents] if parent.is_relative_to(self.output)):
                raise ValueError('Source-test destination must not use symlinks: '+relative)
            save_bytes(target,source.read_bytes())
        save_json(previous,self.manifest)
        # Reuse the workspace's Playwright runtime, adding only additional declared
        # source-test dependencies. Never run package scripts from the source bundle.
        source_package = self.source/'package.json'
        if source_package.is_file():
            declared = json.loads(source_package.read_text(encoding='utf-8-sig'))
            path = self.output/'package.json'
            package = json.loads(path.read_text(encoding='utf-8-sig'))
            for section in ('dependencies','devDependencies'):
                for name,version in declared.get(section,{}).items():
                    if name not in package.get('dependencies',{}) and name not in package.get('devDependencies',{}):
                        package.setdefault('devDependencies',{})[name] = version
            save_json(path,package)

    def selected(self, requirements):
        return sorted({path for rid in requirements for path in self.bindings.get(rid,[])})

    def verify(self):
        changed = [relative for relative,digest in self.files.items()
            if not (self.output/relative).is_file() or (self.output/relative).is_symlink()
            or not (self.output/relative).resolve().is_relative_to(self.output.resolve())
            or hashlib.sha256((self.output/relative).read_bytes()).hexdigest()!=digest]
        if changed:
            raise ValueError('Supplied tests/support/config are readonly; restore the source copies: '+', '.join(changed[:8]))

    def fingerprints(self, rid):
        selected = self.bindings.get(rid,[])
        # Helpers/config affect all consumers; unrelated spec edits need not rebuild
        # every requirement. A newly added same-ID spec changes this node's inputs.
        return {'tests':selected,'files':{path:digest for path,digest in self.files.items()
            if path in selected or path not in self.specs}}

    def coverage(self, executed):
        cases = executed.get('cases',[])
        files = {str(case.get('file','')).replace('\\','/') for case in cases}
        def observed(path):
            suffix = path.split('frontend/',1)[-1]
            source_relative = Path(path).relative_to(ROOT).as_posix()
            return any(name in {path,suffix,source_relative} or name.endswith('/'+suffix) or name.endswith('/'+source_relative) for name in files)
        not_executed = [path for path in self.specs if not observed(path)]
        return {'status':'FAILED' if not_executed else 'GREEN',
            'basis':'Immutable source tests selected by requirement ID, not generated SCN assertions',
            'missing_requirements':[],'missing_scenarios':[],
            'unexecuted_test_files':not_executed,'unmatched_test_ids':self.unmatched,
            'note':'Only published source test files require execution. Other requirements complete through implementation; no tests are generated.'}


def prepare_source_e2e(output, backend, catalog, arc_dir):
    """Adapt only the host launcher; source specs, support and config stay byte-identical."""
    from infrastructure.stages.frontend.triggers.e2e_runtime import prepare_e2e, CONFIG, CONFIG_SOURCE, RUNNER, RUNNER_SOURCE
    prepare_e2e(output,backend)
    catalog.publish(arc_dir)
    config = next((path for path in catalog.files if Path(path).name in
        {'playwright.config.ts','playwright.config.js','playwright.config.mjs','playwright.config.mts','playwright.config.cts'}
        and Path(path).parent.as_posix()==ROOT),None)
    if config:
        specifier = './'+Path(config).relative_to('frontend').as_posix()
        wrapper = ('import sourceModule from '+json.dumps(specifier)+';\n'
            'const sourceConfig = (sourceModule as unknown as { default?: import("@playwright/test").PlaywrightTestConfig }).default ?? sourceModule;\n'+CONFIG_SOURCE)
    else:
        wrapper = 'const sourceConfig: import("@playwright/test").PlaywrightTestConfig = {};\n'+CONFIG_SOURCE
    wrapper = wrapper.replace('export default defineConfig({','export default defineConfig({\n  ...sourceConfig,')
    wrapper = wrapper.replace('testDir: "./tests/e2e"','testDir: "./tests/e2e/source"')
    wrapper = wrapper.replace('timeout: 30000, expect: { timeout: 5000 }, reporter: "json",',
        'timeout: sourceConfig.timeout ?? 30000, expect: sourceConfig.expect ?? { timeout: 5000 }, reporter: "json",')
    wrapper = wrapper.replace('use: { baseURL:', 'use: { ...sourceConfig.use, storageState: undefined, proxy: undefined, baseURL:')
    wrapper = wrapper.replace('fullyParallel: false, retries: 0, forbidOnly: true,',
        'fullyParallel: false, retries: 0, forbidOnly: true, updateSnapshots: "none",\n'
        '  projects: sourceConfig.projects?.map(project => ({ ...project, testDir: "./tests/e2e/source", '
        'use: { ...sourceConfig.use, ...project.use, storageState: undefined, proxy: undefined, '
        'baseURL: `http://127.0.0.1:${frontendPort}` } })),')
    # No remote browser session/proxy may bypass login against the newly built app.
    runner = RUNNER_SOURCE.replace('ARC_E2E_DB_FILE: join(directory, "app.db")',
        'ARC_E2E_DB_FILE: join(directory, "app.db"), E2E_BASE_URL: `http://127.0.0.1:${frontend}`, '
        'E2E_STORAGE_STATE: "", E2E_PROXY: ""')
    save_text(output/CONFIG,wrapper)
    save_text(output/RUNNER,runner)


class SourceE2EChecks(E2EChecks):
    def __init__(self, output, catalog):
        import os
        super().__init__(output,timeout=int(os.getenv('SOURCE_TEST_TIMEOUT_SECONDS','1800')))
        if self.timeout<=0:
            raise ValueError('SOURCE_TEST_TIMEOUT_SECONDS must be positive')
        self.catalog = catalog

    def typecheck(self, files, full_source=True):
        self.catalog.verify()
        # The published suite runs through its Playwright transform, exactly as
        # declared by the source package. Do not impose the app's strict TS policy
        # on external test helpers; only production frontend sources are compiled here.
        return super().typecheck([],full_source=full_source)

    def tests(self, files):
        self.catalog.verify()
        if not set(files)<=set(self.catalog.specs):
            raise ValueError('Run only supplied source tests identified by the source-test manifest')
        return super().tests(files)

    def test_filters(self, files):
        import re
        return [re.escape(path) for path in files]
