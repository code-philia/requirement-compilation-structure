"""Hybrid lexical and same-mode persistent-effect retrieval over accepted backend code."""

import json
from infrastructure.shared.rag.bm25 import rank


class BackendRetriever:
    @staticmethod
    def summary(record):
        """Discovery metadata only; exact interfaces are fetched for selected IDs."""
        result = {key: record[key] for key in
            ('kind', 'name', 'description', 'signature', 'implementation', 'callees') if key in record}
        result['effect_counts'] = {mode: len(record.get(mode, [])) for mode in ('read', 'write')}
        return result

    def retrieve(self, query, required, graph, top_k=6):
        if top_k < 1:
            raise ValueError('top_k must be positive')
        result = {'apis': {}, 'modules': {}, 'matches': {}, 'caller_context': {}}
        wanted = {mode: set(required.get(mode, [])) for mode in ('read', 'write')}
        denominator = sum(map(len, wanted.values()))
        for kind in ('apis', 'modules'):
            records = graph.get(kind, {})
            documents = {key: key + ' ' + json.dumps({k: v for k, v in record.items()
                if k not in {'callers', 'status'}}, ensure_ascii=False) for key, record in records.items()}
            lexical = rank(query, documents, top_k)
            effects = []
            for key, record in records.items():
                shared = {mode: sorted(wanted[mode] & set(record.get(mode, []))) for mode in wanted}
                count = sum(map(len, shared.values()))
                if count:
                    extra_writes = sorted(set(record.get('write', [])) - wanted['write'])
                    effects.append({'symbol': key, 'coverage': round(count / denominator, 4),
                        'shared_read': shared['read'], 'shared_write': shared['write'],
                        'extra_write': extra_writes, 'covers_required': count == denominator})
            effects.sort(key=lambda item: (-item['coverage'], len(item['extra_write']), item['symbol']))
            selected = list(dict.fromkeys([match['symbol'] for match in effects[:top_k]] + [match['symbol'] for match in lexical]))
            result[kind] = {key: self.summary(records[key]) for key in selected}
            result['matches'][kind] = {'bm25': lexical, 'obligation': effects[:top_k]}
        # Do not expand every candidate's full call tree into the initial context.
        # get_capabilities retrieves exact I/O and the callee closure after selection.
        records = {**graph.get('apis', {}), **graph.get('modules', {})}
        for record in [*result['apis'].values(), *result['modules'].values()]:
            for key in record.get('callers', []):
                if key in records:
                    result['caller_context'][key] = self.summary(records[key])
        result['detail_instruction'] = ('Candidates are summaries, not complete contracts. Batch selected IDs in '
            'get_capabilities before reuse to inspect exact input/output, guards, effects and callee definitions.')
        return result
