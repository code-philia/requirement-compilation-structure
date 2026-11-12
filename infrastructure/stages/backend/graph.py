"""Canonical reusable backend capabilities; derived effects, callers and frontend handoff."""

from copy import deepcopy
from pathlib import PurePosixPath
import json

from infrastructure.utils.files import save_json


def empty_graph():
    return {'version': 1, 'apis': {}, 'modules': {}, 'requirements': {}, 'requirement_modules': {}}


def roots(graph, rid):
    return list(dict.fromkeys([*graph['requirements'].get(rid, []), *graph['requirement_modules'].get(rid, [])]))


def closure(graph, identities):
    records = {**graph['apis'], **graph['modules']}
    selected, pending = {}, list(identities)
    while pending:
        key = pending.pop()
        if key in selected or key not in records:
            continue
        selected[key] = records[key]
        pending.extend(records[key].get('callees', []))
    return selected


def refresh_graph(graph, schema):
    """Resolve actual symbols/edges and derive inclusive effects without exact-write gates."""
    if set(graph['apis']) & set(graph['modules']):
        raise ValueError('API and module IDs must be distinct')
    records = {**graph['apis'], **graph['modules']}
    symbols = {name + '.' + key for name, entity in schema['entities'].items() for key in entity['fields']}
    routes = {}
    for key, record in records.items():
        record['callees'] = list(dict.fromkeys(record.get('callees', [])))
        missing = set(record.get('callees', [])) - graph['modules'].keys()
        if missing:
            raise ValueError(f'{key}: define missing module callees {sorted(missing)} before implementation')
        record['callers'] = []
        for mode in ('read', 'write'):
            direct = sorted(set(record.get('direct_' + mode, [])))
            if set(direct) - symbols:
                raise ValueError(f'{key}: unknown {mode} symbols {sorted(set(direct)-symbols)}; use the completed schema')
            record['direct_' + mode], record[mode] = direct, list(direct)
        path = PurePosixPath(record['implementation'])
        if path.is_absolute() or '..' in path.parts or path.parts[:2] != ('backend', 'src') or path.suffix != '.ts':
            raise ValueError(f'{key}: implementation must identify an actual backend/src/*.ts file')
        if key in graph['apis']:
            signature = record['signature']
            method, route = signature['method'], signature['path']
            if method not in {'GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS'} or not route.startswith('/api/') or any(c in route for c in '?# \n'):
                raise ValueError(f'{key}: use a data API method/path under /api/')
            if (method, route) in routes:
                raise ValueError(f'{key}: {method} {route} already belongs to {routes[(method,route)]}; reuse/update that API')
            routes[(method, route)] = key
    for key, record in records.items():
        for callee in record.get('callees', []):
            graph['modules'][callee]['callers'].append(key)
    for record in records.values():
        record['callers'] = sorted(set(record['callers']))
    # Monotone union reaches a fixed point even for a source-required recursive helper.
    changed = True
    while changed:
        changed = False
        for record in records.values():
            for mode in ('read','write'):
                values = sorted(set(record[mode]) | {field for child in record.get('callees', []) for field in graph['modules'][child][mode]})
                if values != record[mode]:
                    record[mode], changed = values, True
    for section, kind in (('requirements','apis'), ('requirement_modules','modules')):
        for rid, identities in graph[section].items():
            missing = set(identities) - graph[kind].keys()
            if missing:
                raise ValueError(f'{rid}: undefined {kind} association {sorted(missing)}')
    return graph


def coverage(graph, rid, required):
    records = closure(graph, roots(graph, rid)).values()
    records = list(records)
    return {mode: sorted(set(required.get(mode, [])) - {field for record in records for field in record.get(mode, [])})
        for mode in ('read', 'write')}


def publish_graph(arc_dir, graph):
    """Only accepted code is discoverable; HTTP and internal operations stay distinct."""
    save_json(arc_dir / 'backend_graph.json', graph)
    save_json(arc_dir / 'backend_apis.json', graph)
    endpoints = {key: {**deepcopy(record), 'usage': json.dumps({'input': record['input'], 'output': record['output'],
        'errors': record.get('errors', [])}, ensure_ascii=False)} for key, record in graph['apis'].items()}
    save_json(arc_dir / 'backend_endpoints.json', {'apis': endpoints, 'requirements': graph['requirements']})
    save_json(arc_dir / 'backend_capabilities.json', {'modules': graph['modules'], 'requirements': graph['requirement_modules']})
    inventory = {'apis': endpoints, 'modules': graph['modules'], 'requirements': graph['requirements'],
        'module_requirements': graph['requirement_modules']}
    save_json(arc_dir.parent / 'backend/src/api/endpoints.json', inventory)
    for kind, filename in (('apis','backend_implementation_files.json'), ('modules','backend_module_implementation_files.json')):
        save_json(arc_dir / filename, {key: record['implementation'] for key, record in graph[kind].items()})
