"""Bounded, on-demand access to compiler-owned global state."""

import json
from copy import deepcopy

from infrastructure.shared.agent.files import source_paths
from infrastructure.shared.rag.bm25 import tokenize
from infrastructure.utils.files import read_artifact

DISCOVERY_RULES = '''Context contains selected excerpts, never a complete global inventory.
Use the supplied task records first. Query only a specific missing fact needed for the
current decision; do not search to reconfirm definitions already supplied or retained.
When evidence is missing, return only {"context_request": {"kind": "schema",
"query": "session credential"}} to discover candidates, or use "ids": ["Account.id"]
to read exact records. Available kinds are listed in context_kinds.
context_request is an ordinary JSON field, NOT a native tool. Never serialize it as
DSML, XML, invoke/parameter tags or a provider tool-call block. For example, when page
is an advertised kind, search shelves by returning exactly:
{"context_request":{"kind":"page","query":"shelves"}}
Do not put this object inside tags, Markdown or a JSON string.
Only those advertised kinds are supported; examples below do not enable other scopes.
Search returns IDs/descriptions, not definitions, except requirement searches return complete records.
Read needed IDs before modifying or calling other kinds of records.
Each query searches only its named kind; do not search unrelated collections for context.
Use offset to inspect another search page. A miss is not proof of absence. Search
shared concepts before creating new entities/APIs; reuse canonical definitions.
For schema, read Entity.field for a narrow field definition; for large pages read
ui_element IDs. kind=file supports exact relative paths or keyword discovery.
For a file excerpt, supply "start_line": 10 and "end_line": 40 alongside ids.
Lines are 1-based and inclusive; end_line may be omitted to read through EOF.
Excerpts return content, start_line, end_line and total_lines. File-writing agents use
read_file instead of kind=file exact reads; semantic design tasks may use these excerpts.
kind=requirement reads original requirement scenarios; kind=test_requirement with a
test file path as an ID finds its original requirement owner IDs. Read the relevant requirement before
changing a regression test; never infer its intended behavior from implementation.
Exact records are retained in context_records and search candidates in context_candidates
for the current task. File-editing tasks
also retain read_file excerpts in read_files. Use retained evidence instead of querying
it again. Return your normal stage output when enough evidence is available.
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
        self.evidence = {}
        self.candidates = {}

    def resolve(self, query):
        try:
            result = self.index.query(query)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
            raise ValueError(f'Invalid context_request {query!r}: {error}. '
                f'Available kinds: {list(self.index.records())}. '
                'Correct the query or return the normal stage output.') from error
        kind = result.get('kind')
        for candidate in result.get('candidates', []):
            if candidate['id'] not in self.evidence.get(kind, {}):
                self.candidates.setdefault(kind, {})[candidate['id']] = deepcopy(candidate)
        if result.get('records'):
            self.evidence.setdefault(kind, {}).update(deepcopy(result['records']))
            for identity in result['records']:
                self.candidates.get(kind, {}).pop(identity, None)
        return self.observe(result)

    def observe(self, result):
        """Apply the same no-progress feedback to semantic queries and file reads."""
        fingerprint = json.dumps(result, sort_keys=True, ensure_ascii=False)
        count = self.results.get(fingerprint, 0) + 1
        self.results[fingerprint] = count
        if count >= 3:
            raise DiscoveryStalled('Discovery returned the same evidence repeatedly. '
                'Read different relevant evidence or return the task output.')
        if count == 2:
            result = {**result, 'next_action': 'These results were already supplied. '
                'Read different evidence or produce the task output.'}
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
        ranged = 'start_line' in request or 'end_line' in request
        if ranged:
            if kind != 'file' or ids is None:
                raise ValueError('Line ranges require kind=file and exact ids')
            start, end = request.get('start_line', 1), request.get('end_line')
            if type(start) is not int or start < 1 or ('end_line' in request and
                    (type(end) is not int or end < start)):
                raise ValueError('Line numbers must be positive integers with end_line >= start_line')
        if ids is not None:
            if not isinstance(ids, list) or any(not isinstance(identity, str) for identity in ids):
                raise ValueError('ids must be an array of strings')
            found = {}
            for identity in ids:
                if kind == 'file':
                    if identity not in records:
                        continue
                    path = self.output / identity
                    if path.is_symlink() or not path.resolve().is_relative_to(self.output.resolve()):
                        raise ValueError('File must be inside the project')
                    content = path.read_text(encoding='utf-8-sig')
                    if ranged:
                        lines = content.splitlines(keepends=True)
                        last = min(end if end is not None else len(lines), len(lines))
                        found[identity] = {'content': ''.join(lines[start - 1:last]),
                            'start_line': start, 'end_line': last, 'total_lines': len(lines)}
                    else:
                        found[identity] = content
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
            if kind == 'requirement':
                result['records'] = {item['id']: deepcopy(records[item['id']]) for item in candidates}
                del result['candidates']
        return {'kind': kind, **result}


def project_index(output, *, kinds, file_roots=()):
    """Expose only stage-selected collections and source directories, rebuilt on demand."""
    from infrastructure.stages.requirements.tree import RequirementTree
    from infrastructure.stages.backend.context import requirement_context
    from infrastructure.stages.frontend.ui.design import owners, data_symbols

    def artifact(name, default):
        return read_artifact(output / '.arc', name) if (output / '.arc' / name).is_file() else default

    def records():
        result = {}
        backend_tests = 'test_requirement' in kinds and any(root.startswith('backend/') for root in file_roots)
        frontend_tests = 'test_requirement' in kinds and any(root.startswith('frontend/') for root in file_roots)
        if 'schema' in kinds:
            result['schema'] = artifact('db_schema.json', {'entities': {}})['entities']
        if 'api' in kinds or backend_tests:
            backend = artifact('backend_apis.json', {'apis': {}, 'requirements': {}})
            if 'api' in kinds:
                result['api'] = backend['apis']
        if any(kind in kinds for kind in ('page', 'ui_element', 'ui_data')) or frontend_tests:
            ui = artifact('ui_design.json', {'pages': {}, 'elements': {}, 'requirements': {}})
            if 'page' in kinds:
                result['page'] = ui['pages']
            if 'ui_element' in kinds:
                result['ui_element'] = ui['elements']
            if 'ui_data' in kinds:
                result['ui_data'] = data_symbols(ui['elements'])
        if 'trigger' in kinds:
            result['trigger'] = artifact('frontend_triggers.json', {'triggers': {}})['triggers']
        if 'convention' in kinds:
            result['convention'] = artifact('shared_conventions.json', {})
        if 'requirement' in kinds or 'test_requirement' in kinds:
            tree = RequirementTree(artifact('requirements.json', {'id': 'ROOT'}))
            requirements = {rid: requirement_context(tree, rid) for rid in tree.leaves}
            if 'requirement' in kinds:
                result['requirement'] = requirements
        if 'test_requirement' in kinds:
            paths = artifact('implementation_paths.json', {})
            test_owners = {}
            if backend_tests:
                for aid, path in paths.get('backend_test', {}).items():
                    test_owners[path] = [rid for rid, aids in backend['requirements'].items()
                        if aid in aids and rid in requirements]
            if frontend_tests:
                for rid, path in paths.get('e2e_test', {}).items():
                    test_owners[path] = [rid] if rid in requirements else []
                for pid in ui['pages']:
                    path = f'frontend/tests/ui/{pid}.spec.ts'
                    test_owners[path] = [rid for rid in owners(ui, pid) if rid in requirements]
            prefixes = tuple(root + '/' for root in file_roots)
            result['test_requirement'] = {path: ids for path, ids in test_owners.items()
                if path.startswith(prefixes)}
        if 'file' in kinds:
            result['file'] = {path: {} for root in file_roots for path in source_paths(output, root)}
        return result

    return ContextIndex(records, output)
