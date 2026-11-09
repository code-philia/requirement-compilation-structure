"""Versioned discovery results and feedback for queries yielding no new evidence."""

import hashlib
import json

from infrastructure.shared.agent.files import source_paths


def refresh_paths(files):
    for scope in files.scope:
        files.available_paths.update(source_paths(files.output, scope))


def version(files, paths):
    digest = hashlib.sha256()
    remaining = 8_000_000
    for relative in paths:
        digest.update(relative.encode())
        path = files.path(relative)
        if not path.is_file():
            digest.update(b'missing')
            continue
        stat = path.stat()
        if stat.st_size <= min(remaining, 1_000_000):
            digest.update(hashlib.sha256(path.read_bytes()).digest())
            remaining -= stat.st_size
        else:
            digest.update(str((stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)).encode())
    return digest.hexdigest()


def query_result(files, tool, arguments, paths, execute):
    """Cache only authorized observations; changed content/inventory gets a new key."""
    snapshot = version(files, paths)
    signature = json.dumps([tool, arguments, snapshot], sort_keys=True, ensure_ascii=False)
    key = 'query-' + hashlib.sha256(signature.encode()).hexdigest()[:20]
    cache = files.discovery_cache
    if key in cache:
        result = cache[key]
        cached = True
    else:
        result = execute()
        cache[key] = result
        cached = False
        # Bound model-visible evidence; evicted results can be retrieved normally again.
        while len(cache) > 16 or (len(cache) > 1 and sum(len(json.dumps(v, ensure_ascii=False)) for v in cache.values()) > 32000):
            cache.pop(next(iter(cache)))
    facts = set()
    if tool == 'list_files':
        facts.update(('path', path) for path in result['paths'])
    else:
        for match in result['matches']:
            facts.update(('line', match['path'], row['line_number'], row['text']) for row in match['context'])
    novel = facts - files.discovery_seen
    files.discovery_seen.update(facts)
    files.discovery_no_progress = 0 if novel else files.discovery_no_progress + 1
    response = {**result, 'cache_id': key, 'cached': cached, 'new_evidence': len(novel)}
    if cached:
        response = {'cache_id': key, 'cached': True,
            'context_reference': f'discovery_cache[{key}]', 'new_evidence': 0}
    if files.discovery_no_progress >= 2:
        response['next_action'] = (
            'These queries yielded no new evidence. Reuse supplied files, test_tool_reference, '
            'read_files and discovery_cache. State the exact missing symbol/line if essential; '
            'otherwise implement now or report a concrete source/runtime blocker.')
        response['no_progress_queries'] = files.discovery_no_progress
    return response
