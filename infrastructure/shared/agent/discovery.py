"""Bounded, on-demand access to compiler-owned global state."""

import json
from copy import deepcopy

from infrastructure.shared.agent.files import source_paths
from infrastructure.shared.rag.bm25 import tokenize
from infrastructure.utils.files import read_artifact

DISCOVERY_RULES = '''Context contains selected excerpts, never a complete global inventory.
When evidence is missing, return only {"context_request": {"kind": "schema",
"query": "session credential"}} to discover candidates, or use "ids": ["Account.id"]
to read exact records. Available kinds are listed in context_kinds. Search returns
IDs/descriptions, not definitions; read needed IDs before modifying or calling them.
Use offset to inspect another search page. A miss is not proof of absence. Search
shared concepts before creating new entities/APIs; reuse canonical definitions.
For schema, read Entity.field for a narrow field definition; for large pages read
ui_element IDs. kind=file supports exact relative paths or keyword discovery.
kind=requirement reads original requirement scenarios; kind=test_requirement with a
test file path as an ID finds its original requirement owner IDs. Read the relevant requirement before
changing a regression test; never infer its intended behavior from implementation. Query results replace
previous results. Return your normal stage output when enough evidence is available.
There is no fixed query-count or character cap. Prefer exact reads after candidate
searches. Do not repeat searches returning the same candidates: read their IDs, or
produce the stage output using the available evidence. Query errors are feedback,
not evidence that an object is absent.'''


class DiscoveryStalled(ValueError):
    """Repeated identical results need a proposal or different evidence, not more searches."""


class DiscoverySession:
    """Allow as many useful queries as needed; return malformed queries as feedback."""

    def __init__(self, index):
        self.index = index
        self.results = {}

    def resolve(self, query):
        try:
            result = self.index.query(query)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
            result = {'error': str(error), 'context_kinds': list(self.index.records()),
                'notice': 'Correct the query or return the normal stage output.'}
        fingerprint = json.dumps(result, sort_keys=True, ensure_ascii=False)
        count = self.results.get(fingerprint, 0) + 1
        self.results[fingerprint] = count
        if count >= 3:
            raise DiscoveryStalled('Discovery returned the same evidence repeatedly. '
                'Read specific candidate IDs, change the evidence sought, or return the normal stage output. '
                'The query count is not limited; this search is making no progress.')
        if count == 2:
            result = {**result, 'next_action': 'These results were already supplied. '
                'Read exact candidate IDs instead of repeating searches, or produce the stage output.'}
        return result


class ContextIndex:
    """Keep complete collections in the host; expose small candidate pages and exact reads."""
    def __init__(self, collections, output=None):
        self.collections = collections
        self.output = output

    def records(self):
        return self.collections() if callable(self.collections) else self.collections

    def query(self, request):
        collections = self.records()
        kind = request['kind']
        records = collections[kind]
        ids = request.get('ids')
        if ids is not None:
            if not isinstance(ids, list) or any(not isinstance(identity, str) for identity in ids):
                raise ValueError('ids must be an array of strings')
            found = {}
            for identity in ids:
                if kind == 'file':
                    if identity not in records:
                        continue
                    found[identity] = (self.output / identity).read_text(encoding='utf-8-sig')
                elif kind == 'schema' and '.' in identity:
                    entity, field = identity.split('.', 1)
                    if entity in records and field in records[entity]['fields']:
                        found[identity] = records[entity]['fields'][field]
                elif identity in records:
                    if kind == 'test_requirement':
                        offset = max(0, int(request.get('offset', 0)))
                        owners = records[identity]
                        found[identity] = {'requirement_ids': owners[offset:offset + 6],
                            'next_offset': offset + 6 if offset + 6 < len(owners) else None}
                    else:
                        found[identity] = records[identity]
            result = {'records': deepcopy(found), 'missing': [key for key in ids if key not in found]}
        else:
            words = set(tokenize(request['query']))
            if not words:
                raise ValueError('Provide a nonempty discovery query')
            scores = []
            for key, record in records.items():
                text = key + ' ' + json.dumps(record, ensure_ascii=False)
                score = len(words.intersection(tokenize(text)))
                if request['query'].lower() in text.lower():
                    score += 1
                if score:
                    scores.append((-score, key))
            scores.sort()
            offset = max(0, int(request.get('offset', 0)))
            candidates = []
            for _, key in scores[offset:offset + 6]:
                value = records[key]
                description = value.get('description', value.get('name', '')) if isinstance(value, dict) else ''
                candidates.append({'id': key, 'description': str(description)[:300]})
            result = {'candidates': candidates, 'next_offset': offset + 6 if offset + 6 < len(scores) else None,
                'notice': 'Lexical candidates only. A miss does not establish absence.'}
        return {'kind': kind, **result}


def project_index(output):
    """Rebuild on demand so queries see current accepted artifacts and files."""
    from infrastructure.stages.requirements.tree import RequirementTree
    from infrastructure.stages.backend.context import requirement_context
    from infrastructure.stages.frontend.ui.design import owners
    def artifact(name, default):
        return read_artifact(output / '.arc', name) if (output / '.arc' / name).is_file() else default
    def records():
        schema = artifact('db_schema.json', {'entities': {}})
        backend = artifact('backend_apis.json', {'apis': {}, 'requirements': {}})
        ui = artifact('ui_design.json', {'pages': {}, 'elements': {}, 'bindings': {}, 'requirements': {}})
        triggers = artifact('frontend_triggers.json', {'triggers': {}})
        tree = RequirementTree(artifact('requirements.json', {'id': 'ROOT'}))
        requirements = {rid: requirement_context(tree, rid) for rid in tree.requirements}
        paths = artifact('implementation_paths.json', {})
        test_owners = {}
        for rid, path in paths.get('e2e_test', {}).items():
            test_owners[path] = [rid] if rid in requirements else []
        for aid, path in paths.get('backend_test', {}).items():
            test_owners[path] = [rid for rid, aids in backend['requirements'].items()
                if aid in aids and rid in requirements]
        for pid in ui['pages']:
            test_owners[f'frontend/tests/ui/{pid}.spec.ts'] = [rid for rid in owners(ui, pid) if rid in requirements]
        # Owners can themselves be numerous: search/read individual requirements when necessary.
        return {'schema': schema['entities'], 'api': backend['apis'], 'page': ui['pages'],
            'ui_element': ui['elements'], 'binding': ui['bindings'], 'trigger': triggers['triggers'],
            'requirement': requirements, 'test_requirement': test_owners,
            'convention': artifact('shared_conventions.json', {}),
            'file': {path: {} for root in ('frontend/src', 'frontend/tests', 'backend/src', 'backend/tests')
                for path in source_paths(output, root)}}
    return ContextIndex(records, output)
