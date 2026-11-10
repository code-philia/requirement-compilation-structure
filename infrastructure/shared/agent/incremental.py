"""Per-requirement accepted checkpoints with source, dependency and file invalidation."""

import hashlib
import json
import re
from pathlib import Path

from infrastructure.shared.agent.context import related_files
from infrastructure.utils.files import save_json

VERSION = 3
SHARED = {'backend/src/api/compiled-modules.ts', 'backend/src/api/endpoints.json', 'backend/src/api/register.ts', 'backend/src/app.ts', 'backend/src/server.ts',
          'frontend/src/main.tsx', 'frontend/src/App.tsx'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class RequirementCheckpoints:
    def __init__(self, arc_dir, stage, raw, inputs):
        self.arc, self.output, self.stage = arc_dir, arc_dir.parent, stage
        self.path = arc_dir / ('incremental_' + stage + '.json')
        try:
            state = json.loads(self.path.read_text())
        except (OSError, ValueError):
            state = {}
        self.records = state.get('records', {}) if state.get('version') == VERSION else {}
        self.nodes, self.parents = {}, {}
        def visit(node, parent=None):
            self.nodes[node['id']] = node
            self.parents[node['id']] = parent
            for child in node.get('children', []) or []:
                visit(child, node['id'])
        visit(raw)
        self.inputs = inputs
        self.data = raw.get('data', [])
        executable = {rid for rid, node in self.nodes.items() if not node.get('children')
            and (stage != 'backend' or rid in self.records or self.inputs(rid).get('apis') or self.inputs(rid).get('capabilities'))}
        self.rebuild = {rid for rid in executable if not self.valid(rid)}
        def leaves(identity):
            children = self.nodes.get(identity, {}).get('children', []) or []
            return set().union(*(leaves(child['id']) for child in children)) if children else {identity}
        while True:
            affected = {rid for rid in executable
                if set().union(*(leaves(dep) for dep in self.nodes[rid].get('dependencies', []))) & self.rebuild}
            if affected <= self.rebuild:
                break
            self.rebuild.update(affected)

    def source_hash(self, rid):
        node = self.nodes[rid]
        # Original requirement and explicit dependency text remain the source authority.
        dependencies, pending = {}, list(node.get('dependencies', []))
        while pending:
            dep = pending.pop()
            if dep in dependencies or dep not in self.nodes:
                continue
            dependencies[dep] = self.nodes[dep]
            pending.extend(self.nodes[dep].get('dependencies', []))
        ancestors, current = {}, self.parents.get(rid)
        while current:
            ancestors[current] = {key: value for key, value in self.nodes[current].items() if key != 'children' and not (key == 'data' and isinstance(value, list))}
            current = self.parents.get(current)
        related = [node, *dependencies.values(), *ancestors.values()]
        required_data = {key for item in related if isinstance(item.get('data'), dict)
            for key in item['data'].get('requires', [])}
        data = [row for row in self.data if row.get('id') in required_data or row.get('entity') == 'test account']
        return digest({'node': node, 'dependencies': dependencies, 'ancestors': ancestors, 'data': data,
            'inputs': self.inputs(rid)})

    def hashes(self, paths):
        result = {}
        for relative in sorted(set(paths)):
            path = (self.output / relative)
            if not path.resolve().is_relative_to(self.output.resolve()) or path.is_symlink():
                continue
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        return result

    def valid(self, rid):
        record = self.records.get(rid, {})
        return (record.get('entry', {}).get('status') == 'GREEN'
            and record.get('source') == self.source_hash(rid)
            and bool(record.get('files')) and self.hashes(record['files']) == record['files']
            and all((self.output / path).is_file() for path in record.get('required_files', [])))

    def reuse(self, rid):
        if rid in self.rebuild or not self.valid(rid):
            return None
        record = self.records[rid]
        shared = record.get('shared_files', {})
        return {**record['entry'], 'reused_checkpoint': True,
            'needs_regression': self.hashes(shared) != shared}

    def paths(self, rid, extra):
        paths = related_files(self.output, [rid]) | set(extra)
        stage_roots = ('backend/src/',) if self.stage == 'backend' else ('frontend/src/', 'backend/src/')
        paths = {p for p in paths if p.startswith(stage_roots) or p in extra}
        paths.update(p for p in SHARED if p.startswith(stage_roots))
        paths.update({'backend/src/platform/runtime.ts', 'backend/src/platform/types.ts',
            'backend/src/platform/settings.ts', 'backend/src/platform/bootstrap.ts',
            'backend/src/business/platform.ts',
            'backend/src/db/client.ts', 'backend/src/db/initialize.ts', 'backend/src/db/seed.ts'})
        if self.stage == 'frontend':
            paths.update({'frontend/src/auth/RegisterPage.tsx', 'frontend/src/design-system.tsx'})
        paths.update({'package.json', 'package-lock.json'})
        paths.update({'backend/package.json', 'backend/tsconfig.json', 'backend/tsconfig.test.json'})
        if self.stage == 'frontend':
            paths.update({'frontend/package.json', 'frontend/tsconfig.json', 'frontend/vite.config.ts'})
        # Follow actual local helper imports. Do not walk all routes from shared registries.
        common = SHARED | {'backend/src/platform/runtime.ts', 'backend/src/platform/types.ts',
            'backend/src/platform/settings.ts', 'backend/src/platform/bootstrap.ts', 'backend/src/business/platform.ts',
            'backend/src/db/initialize.ts', 'backend/src/db/seed.ts', 'backend/tests/support/context.ts'}
        pending, seen = list(paths - common), set()
        while pending:
            relative = pending.pop()
            if relative in seen:
                continue
            seen.add(relative)
            path = self.output / relative
            if not path.is_file() or path.suffix not in {'.ts', '.tsx', '.js', '.jsx'}:
                continue
            for spec in re.findall(r'(?:from\s*|import\s*\()([\'\"])(\.[^\'\"]+)\1', path.read_text()):
                target = path.parent / spec[1]
                candidates = [target, target.with_suffix('.ts'), target.with_suffix('.tsx'), target / 'index.ts', target / 'index.tsx']
                for child in candidates:
                    if child.is_file() and child.resolve().is_relative_to(self.output.resolve()):
                        item = child.resolve().relative_to(self.output.resolve()).as_posix()
                        if item not in paths:
                            paths.add(item)
                            if item not in common:
                                pending.append(item)
                        break
        return {p for p in paths if (self.output / p).is_file()} | {'package-lock.json', 'npm-shrinkwrap.json'}

    def accept(self, rid, entry, extra=()):
        if entry.get('status') != 'GREEN':
            return
        paths = self.paths(rid, extra)
        common = SHARED | {'backend/src/platform/runtime.ts', 'backend/src/platform/types.ts',
            'backend/src/platform/settings.ts', 'backend/src/platform/bootstrap.ts', 'backend/src/business/platform.ts',
            'backend/src/db/initialize.ts', 'backend/src/db/seed.ts'}
        self.records[rid] = {'source': self.source_hash(rid), 'files': self.hashes(paths - common),
            'shared_files': self.hashes(paths & common),
            'required_files': list(extra), 'entry': dict(entry)}
        save_json(self.path, {'version': VERSION, 'stage': self.stage, 'records': self.records})

    def refresh_accepted(self, entries, extra_for):
        # Call only after successful cumulative regression, so shared-file fingerprints
        # may be advanced for all already accepted consumers without hiding breakage.
        for rid, entry in entries.items():
            if entry.get('status') == 'GREEN':
                self.accept(rid, entry, extra_for(rid))
