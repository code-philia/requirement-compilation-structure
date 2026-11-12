"""Source-derived, bounded backend work groups and independent route registration."""

import hashlib
import re
from pathlib import PurePosixPath

from infrastructure.utils.files import save_text, save_json
from infrastructure.shared.agent.outlines import backend_items

ROOT = 'backend/src/api/register.ts'
AGGREGATOR = 'backend/src/api/compiled-modules.ts'


def implementation_groups(tree, design):
    """Keep requirement dependency order; group adjacent explicit module owners only."""
    modules = tree.backend_foundation.get('global_design', {})
    modules = modules.get('modules', []) if isinstance(modules, dict) else []
    declared = {}
    for item in modules if isinstance(modules, list) else []:
        if not isinstance(item, dict):
            continue
        refs = item.get('requirements', [])
        if isinstance(refs, str):
            refs = [refs]
        for rid in refs if isinstance(refs, list) else []:
            if rid in tree.requirements:
                pending = [rid]
                while pending:
                    key = pending.pop()
                    declared.setdefault(key, item.get('name', rid))
                    pending.extend(tree.children.get(key, []))
    groups = []
    for rid in tree.leaves:
        hints = [item.get('implementation_hint', '') for identity, item in backend_items(design, rid).items()
            if not identity.startswith('platform-')]
        # A generic src/api or src/business directory does not prove shared ownership.
        specific = [hint for hint in hints if isinstance(hint, str) and hint.startswith('backend/src/') and
            (PurePosixPath(hint).suffix or len(PurePosixPath(hint).parts) > 3)]
        owner = str(declared.get(rid) or (specific[0] if specific else rid))
        if groups and groups[-1]['owner'] == owner and len(groups[-1]['requirements']) < 4:
            groups[-1]['requirements'].append(rid)
        else:
            groups.append({'owner': owner, 'requirements': [rid]})
    for group in groups:
        group['id'] = 'module-' + hashlib.sha256(group['owner'].encode()).hexdigest()[:12]
        group['registry'] = f"backend/src/api/modules/{group['id']}/register.ts"
    return groups


def publish_registries(output, groups):
    """Wire one stable aggregator; preserve existing application registrations."""
    unique = {group['id']: group for group in groups}
    for group in unique.values():
        path = output / group['registry']
        if not path.is_file():
            save_text(path, 'import type { Express } from "express";\nimport type Database from "better-sqlite3";\n'
                'export function registerModuleApis(app: Express, connection: Database.Database): void {}\n')
    imports, calls = [], []
    for index, (mid, group) in enumerate(unique.items()):
        imports.append(f'import {{ registerModuleApis as m{index} }} from "./modules/{mid}/register.js";')
        calls.append(f'  m{index}(app, connection);')
    save_text(output / AGGREGATOR, 'import type { Express } from "express";\nimport type Database from "better-sqlite3";\n'
        + '\n'.join(imports) + '\nexport function registerCompiledModules(app: Express, connection: Database.Database): void {\n'
        + '\n'.join(calls) + '\n}\n')
    source = (output / ROOT).read_text()
    match = re.search(r'export function registerApis\s*\(\s*(\w+)\s*:[^,]+,\s*(\w+)\s*:[^)]*\)\s*(?::\s*void)?\s*\{', source)
    wired = bool(re.search(r'\bregisterCompiledModules\s*\(', source))
    if match and not wired:
        source = source[:match.end()] + f'\n  registerCompiledModules({match[1]}, {match[2]});' + source[match.end():]
        wired = True
    if wired and not re.search(r"(?m)^import[^\n]*\bregisterCompiledModules\b[^\n]*from[ \t]+['\"]\./compiled-modules\.js['\"]", source):
        source = 'import { registerCompiledModules } from "./compiled-modules.js";\n' + source
    save_text(output / ROOT, source)
    save_json(output / '.arc/backend_modules.json', {'groups': groups, 'aggregator': AGGREGATOR,
        'root': ROOT, 'wired': wired})
    return wired
