"""Small implementation outlines; source evidence remains the behavioral authority."""

import hashlib
import json
from pathlib import PurePosixPath

from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.files import read_artifact, save_json
from infrastructure.utils.presentation.console import DemoConsole


RULES = '''Produce a short implementation outline for ONE source requirement.
Describe WHAT APIs/pages are needed and WHERE existing or new application code should
implement them. Reuse inventory IDs for shared capabilities; extend their purpose without
losing earlier uses. File locations are suggestions, not exclusive ownership or mandatory
one-file-per-requirement mappings. Prefer actual existing owners if supplied.
Return {"items": {"stable-id": ITEM}, "uses": ["stable-id"], "notes": "short integration notes"}.
Only return new or changed items; uses includes reused items. If no work belongs to this
layer, return empty items/uses and explain why in notes. Never omit source-required work.
Keep it brief: no JSON Schema, P/Q, field-level database effects, component trees, JSX,
component props, event DSL, detailed state machines or tests. The implementation agent
will resolve those details from original scenarios, ER, permissions, processes and UI
references. Do not invent business rules. Include persisted reload/read entrypoints where
needed. Identity/session, permissions and shared navigation must be reused across modules.
An outline is a coordination aid; original requirements remain the acceptance oracle.
'''


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def input_hashes(arc_dir, kind):
    names = ['requirements.json', 'db_schema.json', 'backend_foundation.json']
    if kind == 'frontend':
        names += ['backend_apis.json', 'ui_evidence.json', 'visual_analysis.json']
    return {name: fingerprint(read_artifact(arc_dir, name)) for name in names}


def load_outline(arc_dir, kind):
    plan = read_artifact(arc_dir, kind + '_plan.json')
    if plan.get('input_hashes') != input_hashes(arc_dir, kind) or plan.get('status') != 'GREEN':
        raise ValueError(f'{kind} outline is incomplete or stale; rerun its planning stage')
    return plan


def plan_requirements(arc_dir, kind, tree, contexts, *, inventory=None, pause=False, max_attempts=5):
    """Only check identifiers/locations/references here; implementation owns details."""
    model, console = TextModel(), DemoConsole(pause)
    plan = {'status': 'RUNNING', 'kind': kind, 'input_hashes': input_hashes(arc_dir, kind),
        'items': dict(inventory or {}), 'requirements': {}, 'notes': {}}
    path = arc_dir / (kind + '_plan.json')
    save_json(path, plan)
    if kind == 'backend':
        shape = '''ITEM = {"purpose":"brief business operation", "method":"GET|POST|PUT|PATCH|DELETE",
"path":"/api/...", "implementation_hint":"backend/src/..."}.
No security or workflow DSL here; source authorization and process evidence is supplied
again when implementing. Reuse platform identity endpoints; do not design registration
unless explicitly required by the selected identity strategy.'''
    else:
        shape = '''ITEM = {"purpose":"page/section and its main actions", "route":"/page/:id",
"implementation_hint":"frontend/src/...", "api_ids":["existing backend API IDs"]}.
Describe layout/navigation/forms/important visible states briefly in purpose or notes.
Reuse shared shell/pages and source routes when specified. API IDs refer to the actual
backend inventory. Do not design component trees, props or individual trigger records.
Use Arco; choose components and callback wiring during implementation.'''
    backend = read_artifact(arc_dir, 'backend_apis.json') if kind == 'frontend' else None
    for rid in tree.leaves:
        request = {'requirement': contexts[rid], 'inventory': plan['items'],
            'existing_sources': {key: read_artifact(arc_dir, key) for key in
                ('requirement_files.json', 'backend_implementation_files.json') if (arc_dir / key).is_file()}}
        if backend:
            request['backend_inventory'] = {aid: {'description': api['description'], 'signature': api['signature']}
                for aid, api in backend['apis'].items()}

        def accept(proposal):
            items, uses = proposal['items'], proposal['uses']
            if not isinstance(items, dict) or not isinstance(uses, list) or any(not isinstance(x, str) for x in uses):
                raise ValueError('Outline requires items object and uses ID array')
            if not isinstance(proposal.get('notes'), str) or (not uses and not proposal['notes'].strip()):
                raise ValueError('Explain integration or why this requirement has no work in this layer')
            if kind == 'frontend' and not uses and contexts[rid].get('ui_evidence', {}).get('pages'):
                raise ValueError('This requirement cites published UI pages; retain a page entry for implementation')
            if set(items) - set(uses):
                raise ValueError('Only propose items used by the current requirement')
            for key, item in items.items():
                if not isinstance(key, str) or not key.strip():
                    raise ValueError('Use nonempty stable outline IDs')
                if not isinstance(item, dict) or not isinstance(item.get('purpose'), str) or not item['purpose'].strip():
                    raise ValueError('Each item needs a concise purpose')
                hint = item.get('implementation_hint', '')
                if not isinstance(hint, str) or not hint.startswith(kind + '/src/') or '\\' in hint or '..' in PurePosixPath(hint).parts:
                    raise ValueError('Use a safe suggested application source path')
                route = item.get('path' if kind == 'backend' else 'route')
                if not isinstance(route, str) or not route.startswith('/api/' if kind == 'backend' else '/'):
                    raise ValueError('Supply an API or page route')
                if kind == 'backend':
                    if item.get('method') not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}:
                        raise ValueError('Use a supported HTTP method')
                    if key in (inventory or {}) and item != inventory[key]:
                        raise ValueError('Reuse platform endpoints without changing them')
                else:
                    aids = item.get('api_ids')
                    if not isinstance(aids, list) or any(not isinstance(x, str) or x not in backend['apis'] for x in aids):
                        raise ValueError('Page API IDs must refer to implemented backend contracts')
            if not set(uses) <= set(plan['items']) | set(items):
                raise ValueError('Unknown outline item ID')
            return proposal

        proposal, _ = propose_json(model, RULES + shape, request, accept, console,
            f'{kind.title()} outline {rid}', max_attempts)
        plan['items'].update(proposal['items'])
        plan['requirements'][rid] = list(dict.fromkeys(proposal['uses']))
        plan['notes'][rid] = proposal['notes']
        save_json(path, plan)
    plan['status'] = 'GREEN'
    save_json(path, plan)
    return plan
