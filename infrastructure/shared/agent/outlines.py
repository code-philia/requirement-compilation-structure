"""Small implementation outlines; source evidence remains the behavioral authority."""

import hashlib
import json

from infrastructure.shared.models.text import TextModel
from infrastructure.utils.files import read_artifact, save_json
from infrastructure.utils.presentation.console import DemoConsole


RULES = '''Produce a short implementation outline for ONE source requirement.
Describe WHAT APIs, supporting backend modules or pages are needed and WHERE existing or new application code should
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
        names += ['backend_endpoints.json', 'ui_evidence.json', 'visual_analysis.json']
    return {name: hashlib.sha256((arc_dir / name).read_bytes()).hexdigest() if (arc_dir / name).is_file() else None for name in names}


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


def backend_kind(item, identity=''):
    """Kinds are guidance, not an enum gate; older HTTP outlines keep working."""
    explicit = item.get('kind')
    if not explicit and isinstance(item.get('type'), str) and item.get('type') in {'api', 'http', 'endpoint', 'http_api', 'service', 'repository', 'policy', 'workflow', 'validator', 'utility', 'integration', 'module'}:
        explicit = item['type']
    if isinstance(explicit, str) and explicit.strip():
        value = explicit.strip().lower()
        return 'api' if value in {'http', 'endpoint', 'http_api', 'api'} else value
    signature = item.get('signature') or {}
    if item.get('method') or isinstance(signature, dict) and signature.get('method') or identity.lower().startswith(('api-', 'platform-')):
        return 'api'
    return 'capability' if item.get('needs_implementation_refinement') else 'module'


def backend_items(plan, rid):
    """Include shared dependencies once; cycles/unknown hints never reject design."""
    items, selected, pending = plan.get('items', {}), {}, list(plan.get('requirements', {}).get(rid, []))
    while pending:
        identity = pending.pop(0)
        if identity in selected:
            continue
        item = dict(items.get(identity) or {'purpose': identity, 'unresolved_outline_reference': True})
        item['kind'] = backend_kind(item, identity)
        deps = item.get('depends_on', [])
        deps = [deps] if isinstance(deps, str) else list(deps) if isinstance(deps, dict) else deps if isinstance(deps, list) else []
        item['depends_on'] = list(dict.fromkeys(dep for dep in deps if isinstance(dep, str)))
        selected[identity] = item
        pending.extend(dep for dep in item['depends_on'] if dep not in selected)
    return selected


def plan_requirements(arc_dir, kind, tree, contexts, *, inventory=None, pause=False, max_attempts=5):
    """Collect one proposal per requirement, without design rejection or repair calls."""
    model, console = TextModel(), DemoConsole(pause)
    plan = {'status': 'RUNNING', 'kind': kind, 'input_hashes': input_hashes(arc_dir, kind),
        'items': dict(inventory or {}), 'requirements': {}, 'notes': {}}
    path = arc_dir / (kind + '_plan.json')
    save_json(path, plan)
    if kind == 'backend':
        shape = '''Backend ITEM = {"kind":"api|service|repository|policy|workflow|validator|utility|integration|other source-required module",
"purpose":"short responsibility", "implementation_hint":"backend/src/...",
"depends_on":["existing or proposed capability IDs"], "consumers":["API/module IDs or source-required caller"]}.
Only kind=api needs method/path. A shared module needs responsibility, location and
callers, NOT an invented HTTP endpoint. Export names and detailed interfaces are chosen
while implementing. Reuse shared capabilities across requirements via IDs/dependencies;
only propose useful source-backed modules, no mandatory layered architecture or utility
catalog. Shared code may own calculations, validation, persistence, business operations,
policy adapters or workflow orchestration. Reuse actual existing implementations of
authentication, transactions and auditing when present; otherwise design source-required
shared modules. Do not assume a fixed platform exists. For integrations/background
work, describe real callers/lifecycle only when the source requires them.
No security/workflow DSL or detailed contracts here. Source evidence is supplied again
at implementation. Derive user types and identity endpoints from requirements; do not
invent preset roles, accounts or registration choices.'''
    else:
        shape = '''ITEM = {"purpose":"page/section and its main actions", "route":"/page/:id",
"implementation_hint":"frontend/src/...", "api_ids":["existing backend API IDs"]}.
Describe layout/navigation/forms/important visible states briefly in purpose or notes.
Reuse shared shell/pages and source routes when specified. API IDs refer to the actual
backend inventory. Do not design component trees, props or individual trigger records.
Use Arco; choose components and callback wiring during implementation.
When source requires registration, plan its page against actual designed backend APIs.
Derive selectable user types and role bindings from source evidence, not preset roles.
Reuse existing authentication components/endpoints only when actually supplied.'''
    backend_path = arc_dir / 'backend_endpoints.json'
    backend = read_artifact(arc_dir, backend_path.name) if kind == 'frontend' and backend_path.is_file() else None
    foundation = read_artifact(arc_dir, 'backend_foundation.json')
    plan['global_design'] = foundation.get('global_design', {})
    plan['diagnostics'] = []
    for rid in tree.leaves:
        request = {'requirement': contexts[rid], 'inventory': plan['items'],
            'global_design': plan['global_design'],
            'existing_sources': {key: read_artifact(arc_dir, key) for key in
                ('requirement_files.json', 'backend_implementation_files.json') if (arc_dir / key).is_file()}}
        if backend:
            request['backend_inventory'] = {aid: {'description': api.get('description', aid), 'signature': api.get('signature', {}), 'usage': api.get('usage', '')}
                for aid, api in backend['apis'].items()}

        console.show(f'{kind.title()} outline {rid}',
            'Collect one outline; implementation resolves missing details and associations.')
        proposal = None
        # A malformed outline must not abort all remaining requirements. One short
        # protocol repair, then an explicit source-backed implementation handoff.
        for attempt in range(2):
            try:
                proposal = model.generate_json(RULES + shape, request)
                break
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                diagnostic = {'requirement': rid, 'attempt': attempt + 1,
                    'error_type': type(error).__name__, 'error': str(error)[:1000]}
                plan['diagnostics'].append(diagnostic)
                request['format_repair'] = 'Return one small JSON object with items, uses and notes. No prose or tool tags.'
                console.show(f'{kind.title()} outline {rid} | Recoverable format issue', diagnostic['error'])
        if proposal is None:
            identity = kind + '-source-' + rid
            proposal = {'items': {identity: {
                'purpose': 'Implement original requirement ' + rid,
                'implementation_hint': 'backend/src/api/register.ts' if kind == 'backend' else 'frontend/src/App.tsx',
                'needs_implementation_refinement': True}}, 'uses': [identity],
                'notes': 'Outline response was unusable. Resolve actual APIs/pages and owners from the original requirement and global design during implementation; no behavior is waived.'}

        # Retain the exact response as evidence. Normalization is only an adapter to
        # downstream dictionaries; it must not reject or silently lose model suggestions.
        plan.setdefault('source_proposals', {})[rid] = proposal
        items, uses, notes = collect_outline(proposal, rid)
        if kind == 'backend':
            items = {identity: {**item, 'kind': backend_kind(item, identity)} for identity, item in items.items()}
        plan['items'].update(items)
        for key in uses:
            if key not in plan['items']:
                plan['items'][key] = {'purpose': key, 'unresolved_outline_reference': True}
        plan['requirements'][rid] = uses
        plan['notes'][rid] = notes
        save_json(path, plan)
    plan['status'] = 'READY_WITH_WARNINGS' if plan['diagnostics'] else 'GREEN'
    save_json(path, plan)
    return plan
