"""Canonical cross-requirement decisions owned by API design, not application repair."""

from copy import deepcopy
from infrastructure.utils.files import read_artifact

CONVENTION_RULES = '''shared_conventions are canonical cross-requirement decisions, selected for this task.
Reuse their exact identities, credential transport and observable meanings. API contracts
are the canonical accumulated behavior, not disposable summaries of the latest requirement.
When a NEW cross-API concept first needs a decision (for example session cookie name and
transport, or current-user identity), return optional "conventions": {"stable-id": "concise
normative decision"} alongside the normal API output. Do not invent global conventions
for unrelated future functionality. Reuse existing convention IDs; search kind=convention
when uncertain. Existing conventions stay unchanged unless explicit requirement evidence
requires a coordinated correction. Before changing one, query the affected API contracts
and relevant source requirement scenarios; preserve earlier accepted behavior. Return only
new or deliberately revised conventions, or omit conventions when no change is needed.
Application/test implementation tasks may read these decisions, but do not own their edits.'''


def load_conventions(arc_dir):
    return read_artifact(arc_dir, 'shared_conventions.json') if (arc_dir / 'shared_conventions.json').is_file() else {}


def select_conventions(records, *, fields=(), requirements=()):
    fields, requirements = set(fields), set(requirements)
    return {key: record['description'] for key, record in records.items()
        if fields.intersection(record.get('fields', [])) or requirements.intersection(record.get('requirements', []))}


def merge_conventions(records, proposal, rid, fields):
    """Persist plain model decisions; the compiler maintains their relevance associations."""
    updated = deepcopy(records)
    changes = proposal.get('conventions', {})
    if not isinstance(changes, dict) or any(not isinstance(text, str) for text in changes.values()):
        raise ValueError('conventions must be an object mapping stable IDs to decision strings')
    relevant = select_conventions(updated, fields=fields, requirements=[rid])
    for key in set(changes) | set(relevant):
        record = updated.setdefault(key, {'description': '', 'fields': [], 'requirements': []})
        if key in changes:
            record['description'] = changes[key]
        record['fields'] = sorted(set(record['fields']) | set(fields))
        record['requirements'] = sorted(set(record['requirements']) | {rid})
    return updated


def task_conventions(output, task):
    """Select by current requirement/API dependencies, without sending the global registry."""
    requirements, fields = set(), set()
    def visit(value):
        if isinstance(value, dict):
            identity = value.get('id')
            if isinstance(identity, str):
                requirements.add(identity)
            for mode in ('read', 'write'):
                if isinstance(value.get(mode), list):
                    fields.update(item for item in value[mode] if isinstance(item, str))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(task)
    return select_conventions(load_conventions(output / '.arc'), fields=fields, requirements=requirements)
