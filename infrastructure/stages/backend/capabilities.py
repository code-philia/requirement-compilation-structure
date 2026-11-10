"""Tolerant documentation handoff for HTTP endpoints and non-HTTP capabilities."""

from infrastructure.shared.agent.outlines import backend_kind


def associations(value):
    if not isinstance(value, dict):
        return {}
    return {str(rid): [ids] if isinstance(ids, str) else [str(identity) for identity in ids] if isinstance(ids, list) else []
        for rid, ids in value.items()}


def normalize_inventory(value):
    if not isinstance(value, dict):
        value = {}
    apis, modules = {}, {}
    for section, target in (('modules', modules), ('apis', apis)):
        records = value.get(section, {})
        if isinstance(records, list):
            records = {str(item.get('id') or f'{section}-{index}'): item for index, item in enumerate(records) if isinstance(item, dict)}
        if not isinstance(records, dict):
            continue
        for identity, item in records.items():
            identity = str(identity)
            record = dict(item) if isinstance(item, dict) else {'description': str(item)}
            kind = backend_kind(record, identity) if record.get('kind') or section == 'apis' else 'module'
            record['kind'] = kind
            (apis if kind == 'api' else modules)[identity] = record
    api_uses, module_uses = {}, associations(value.get('module_requirements', {}))
    unresolved = associations(value.get('unresolved_requirements', {}))
    for rid, identities in associations(value.get('requirements', {})).items():
        identities = list(dict.fromkeys([*identities, *unresolved.get(rid, [])]))
        api_uses[rid] = [identity for identity in identities if identity in apis or identity.startswith('platform-')]
        unresolved[rid] = [identity for identity in identities if identity not in apis and identity not in modules and not identity.startswith('platform-')]
        module_uses[rid] = list(dict.fromkeys([*module_uses.get(rid, []), *(identity for identity in identities if identity in modules)]))
    return {'apis': apis, 'requirements': api_uses, 'modules': modules, 'module_requirements': module_uses,
        'unresolved_requirements': {rid: ids for rid, ids in unresolved.items() if ids}}
