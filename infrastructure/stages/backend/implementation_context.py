"""Small, purpose-specific model inputs without discarding source evidence."""

from copy import deepcopy

from infrastructure.stages.backend.context import requirement_context, requirement_schema


def source_context(tree, rid):
    """Keep behavior and evidence once; shared foundation is supplied separately."""
    context = requirement_context(tree, rid)
    context.pop('backend_foundation', None)
    evidence = deepcopy(context.get('backend_evidence', {}))
    if evidence.get('requirement'):
        # Text/scenarios already live in the requirement. Keep exact source bindings.
        evidence['requirement'] = {key: value for key, value in evidence['requirement'].items()
            if key not in {'text', 'name', 'scenarios', 'observed_ui_text', 'children'}}
    context['backend_evidence'] = evidence
    return context


def schema_context(schema, rid):
    """Only table definitions; never repeat ER import metadata or all allocations."""
    return {'entities': requirement_schema(schema, rid),
        'discovery': 'Additional authoritative DDL: backend/src/db/tables/*.sql. '
                     'Read named dependencies if needed; omitted tables are not prohibited.'}


def api_index(items):
    """Transport and source location index, without repeating complete API descriptions."""
    return {key: {field: item[field] for field in (
        'purpose', 'method', 'path', 'implementation_hint', 'signature', 'implementation') if field in item}
        for key, item in items.items()}


def implementation_context(tree, schema, design, rid):
    selected = design.get('requirements', {}).get(rid, [])
    return {'requirement': source_context(tree, rid), 'db_schema': schema_context(schema, rid),
        'api_design': {'items': {aid: design.get('items', {}).get(aid, {'purpose': aid}) for aid in selected},
            'notes': design.get('notes', {}).get(rid, '')},
        'api_inventory': api_index({aid: item for aid, item in design.get('items', {}).items() if aid not in selected}),
        'backend_foundation': tree.backend_foundation,
        'endpoint_documentation': 'backend/src/api/endpoints.json',
        'registry': 'backend/src/api/register.ts'}


def acceptance_context(tree, schema, inventory, rid, oracle, accounts, test_path, support):
    """Tests get source expectations and transport, not a copy of the implementation task."""
    requirement = source_context(tree, rid)
    # The independent original scenarios/description are present in source_expectations.
    requirement.pop('steps', None)
    requirement.pop('description', None)
    selected = set(inventory.get('requirements', {}).get(rid, []))
    selected.update(aid for aid, api in inventory.get('apis', {}).items()
        if api.get('platform_builtin') or aid.startswith('platform-'))
    return {'requirement': requirement, 'source_expectations': oracle,
        'schema': schema_context(schema, rid),
        'implemented_endpoints': {aid: api for aid, api in inventory.get('apis', {}).items() if aid in selected},
        'supporting_endpoint_index': api_index({aid: api for aid, api in inventory.get('apis', {}).items() if aid not in selected}),
        'backend_foundation': tree.backend_foundation,
        'test_path': test_path, 'support_module': support, 'test_accounts': accounts,
        'discovery': 'Read related route handlers/DDL only for a missing transport or fixture fact. '
                     'Endpoint documentation is at backend/src/api/endpoints.json. '
                     'Prior tests and platform runtime are optional references, not required reading.'}
