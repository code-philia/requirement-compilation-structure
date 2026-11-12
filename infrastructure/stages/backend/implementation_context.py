"""Small, purpose-specific model inputs without discarding source evidence."""

from copy import deepcopy
import hashlib

from infrastructure.shared.agent.outlines import backend_items
from infrastructure.stages.backend.context import requirement_context, requirement_schema


def evidence_filename(rid):
    return hashlib.sha256(rid.encode()).hexdigest()[:24] + '.json'


def source_context(tree, rid):
    """Keep behavior and evidence once; shared foundation is supplied separately."""
    context = requirement_context(tree, rid)
    context.pop('backend_foundation', None)
    evidence = deepcopy(context.get('backend_evidence', {}))
    if evidence.get('requirement'):
        # Text/scenarios already live in the requirement. Keep exact source bindings.
        evidence['requirement'] = {key: value for key, value in evidence['requirement'].items()
            if key not in {'text', 'name', 'scenarios', 'observed_ui_text', 'children'}}
    # Ancestors/dependencies are links here, not copies of whole source chapters.
    for key in ('ancestor_context', 'dependency_context'):
        evidence[key] = [{k: item[k] for k in ('id', 'name', 'processes', 'authorization', 'er') if k in item}
            for item in evidence.get(key, [])]
    direct = set(evidence.get('requirement', {}).get('processes', []))
    evidence['processes'] = {pid: process if pid in direct else
        {key: process[key] for key in ('id', 'name', 'source') if key in process}
        for pid, process in evidence.get('processes', {}).items()}
    authorization = evidence.get('authorization', {})
    if authorization:
        authorization.pop('model', None)
        authorization['model_reference'] = 'reference/authorization/model.conf (source policy evidence; implement or reuse its enforcement as required)'
    context['full_evidence_reference'] = 'references/context/' + evidence_filename(rid)
    context['backend_evidence'] = evidence
    return context


def schema_context(schema, rid):
    """Only table definitions; never repeat ER import metadata or all allocations."""
    def compact(entity):
        return {**{key: value for key, value in entity.items() if key != 'fields'},
            'fields': {name: {key: value for key, value in field.items() if key in
                {'type', 'source_type', 'sqlite_type', 'primary_key', 'nullable', 'unique', 'references'}}
                for name, field in entity['fields'].items()}}
    return {'entities': {name: compact(entity) for name, entity in requirement_schema(schema, rid).items()},
        'discovery': 'Additional authoritative DDL: backend/src/db/tables/*.sql. '
                     'Read named dependencies if needed; omitted tables are not prohibited.'}


def api_index(items):
    """Transport and source location index, without repeating complete API descriptions."""
    return {key: {field: item[field] for field in (
        'kind', 'purpose', 'method', 'path', 'implementation_hint', 'signature', 'implementation', 'depends_on', 'consumers', 'exports', 'callers') if field in item}
        for key, item in items.items()}


def implementation_context(tree, schema, design, rid):
    work = backend_items(design, rid)
    selected = set(work)
    return {'requirement': source_context(tree, rid), 'db_schema': schema_context(schema, rid),
        'backend_design': {'items': work,
            'notes': design.get('notes', {}).get(rid, '')},
        'api_inventory': api_index({aid: item for aid, item in design.get('items', {}).items() if aid not in selected
            and (aid.startswith('platform-') or any(aid in design.get('requirements', {}).get(dep, [])
                for dep in tree.raw[rid].get('dependencies', [])))}),
        'backend_foundation': {key: tree.backend_foundation[key] for key in ('enabled', 'identity_model', 'implementation_notes', 'default_boundary', 'registration', 'business_configuration', 'global_design') if key in tree.backend_foundation},
        'endpoint_documentation': 'backend/src/api/endpoints.json',
        'registry': 'backend/src/api/register.ts',
        'business_configuration': tree.backend_foundation.get('business_configuration'),
        'workflow_implementation': 'Implement associated source BPMN, guards and effects in real code; '
            'derive shared workflow owners from the source and actual existing implementation locations.'}


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
        'supporting_endpoint_index': {},
        'backend_foundation': {key: tree.backend_foundation[key] for key in ('enabled', 'default_boundary', 'registration', 'business_configuration', 'global_design') if key in tree.backend_foundation},
        'test_path': test_path, 'support_module': support, 'test_accounts': accounts,
        'discovery': 'Read related route handlers/DDL only for a missing transport or fixture fact. '
                     'Endpoint documentation is at backend/src/api/endpoints.json. '
                     'Prior tests and platform runtime are optional references, not required reading.'}
