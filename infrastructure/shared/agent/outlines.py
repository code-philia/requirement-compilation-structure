"""Small implementation outlines; source evidence remains the behavioral authority."""

import hashlib
import json

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
    return plan


def collect_outline(proposal, rid):
    """Tolerate partial shapes; retain raw values for interpretation during implementation."""
    if not isinstance(proposal, dict):
        proposal = {'items': {rid: {'purpose': str(proposal), 'source_value': proposal}}}
    raw_items = proposal.get('items', {})
    if isinstance(raw_items, list):
        raw_items = {str(item.get('id') or f'{rid}-item-{i}') if isinstance(item, dict)
            else f'{rid}-item-{i}': item for i, item in enumerate(raw_items, 1)}
    elif not isinstance(raw_items, dict):
        raw_items = {rid: raw_items} if raw_items else {}
    items = {}
    for key, value in raw_items.items():
        item = dict(value) if isinstance(value, dict) else {'purpose': str(value), 'source_value': value}
        item.setdefault('purpose', str(key))
        api_ids = item.get('api_ids', [])
        item['api_ids'] = [api_ids] if isinstance(api_ids, str) else (
            [str(aid) for aid in api_ids] if isinstance(api_ids, (list, dict)) else [])
        items[str(key)] = item
    uses = proposal.get('uses', [])
    if isinstance(uses, str):
        uses = [uses]
    elif isinstance(uses, dict):
        uses = list(uses)
    elif not isinstance(uses, list):
        uses = []
    # Every proposed item belongs to this slice even when omitted from uses.
    uses = list(dict.fromkeys([str(key) for key in uses] + list(items)))
    notes = proposal.get('notes', '')
    return items, uses, notes if isinstance(notes, str) else json.dumps(notes, ensure_ascii=False)


def plan_requirements(arc_dir, kind, tree, contexts, *, inventory=None, pause=False, max_attempts=5):
    """Collect one proposal per requirement, without design rejection or repair calls."""
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

        console.show(f'{kind.title()} outline {rid}',
            'Collect one outline; implementation resolves missing details and associations.')
        proposal = model.generate_json(RULES + shape, request)
        # Retain the exact response as evidence. Normalization is only an adapter to
        # downstream dictionaries; it must not reject or silently lose model suggestions.
        plan.setdefault('source_proposals', {})[rid] = proposal
        items, uses, notes = collect_outline(proposal, rid)
        plan['items'].update(items)
        for key in uses:
            if key not in plan['items']:
                plan['items'][key] = {'purpose': key, 'unresolved_outline_reference': True}
        plan['requirements'][rid] = uses
        plan['notes'][rid] = notes
        save_json(path, plan)
    plan['status'] = 'GREEN'
    save_json(path, plan)
    return plan
