"""Bounded, on-demand access to compiler-owned global state."""

import json
from copy import deepcopy

from infrastructure.shared.rag.bm25 import tokenize

DISCOVERY_RULES = '''Design context contains selected excerpts, not a complete global inventory.
Use the supplied records and retrieved candidates first. Query only a specific missing
semantic definition needed for the current design; reuse canonical IDs and definitions.
Return {"context_request":{"kind":"schema","query":"session credential"}} to search,
or {"context_request":{"kind":"schema","ids":["Account.id"]}} for exact definitions.
Available kinds are advertised in context_kinds. context_request is plain JSON, not a
provider-native tool call; never wrap it in DSML/XML, Markdown or a JSON string.
Search returns at most six ID/description candidates with next_offset; requirement
searches include complete records. Read relevant IDs after searching. Use offset for
another page. Lexical search misses do not prove absence.
Exact records remain in context_records; search candidates remain in context_candidates.
Do not repeatedly request retained evidence. Return the normal design output once the
necessary evidence is available. Implementation uses file scopes and does not use queries.'''


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
    def __init__(self, collections):
        self.collections = collections

    def records(self):
        return self.collections() if callable(self.collections) else self.collections

    def query(self, request):
        records = self.records()[request["kind"]]
        kind = request["kind"]
        ids = request.get("ids")
        if ids is not None:
            if not isinstance(ids, list) or any(not isinstance(identity, str) for identity in ids):
                raise ValueError("ids must be an array of strings")
            found = {}
            for identity in ids:
                if kind == "schema" and "." in identity:
                    entity, field = identity.split(".", 1)
                    if entity in records and field in records[entity]["fields"]:
                        found[identity] = records[entity]["fields"][field]
                elif identity in records:
                    found[identity] = records[identity]
            return {"kind": kind, "records": deepcopy(found), "missing": [key for key in ids if key not in found]}
        words = set(tokenize(request["query"]))
        if not words:
            raise ValueError("Provide a nonempty discovery query")
        scores = []
        for key, record in records.items():
            text = key + " " + json.dumps(record, ensure_ascii=False)
            score = len(words.intersection(tokenize(text)))
            if request["query"].lower() in text.lower():
                score += 1
            if score:
                scores.append((-score, key))
        scores.sort()
        offset = max(0, int(request.get("offset", 0)))
        candidates = []
        for _, key in scores[offset:offset + 6]:
            value = records[key]
            description = value.get("description", value.get("name", "")) if isinstance(value, dict) else ""
            candidates.append({"id": key, "description": str(description)[:300]})
        result = {"kind": kind, "candidates": candidates,
            "next_offset": offset + 6 if offset + 6 < len(scores) else None,
            "notice": "Lexical candidates only. A miss does not establish absence."}
        if kind == "requirement":
            result["records"] = {item["id"]: deepcopy(records[item["id"]]) for item in candidates}
            del result["candidates"]
        return result
