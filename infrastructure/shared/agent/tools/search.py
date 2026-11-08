"""Bounded readonly discovery over the task's authorized source inventory."""

from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import PurePosixPath

from .files import FileToolError


def matches_glob(path, pattern):
    if not pattern or pattern.startswith('/') or '\\' in pattern or any(p in {'.','..'} for p in pattern.split('/')):
        raise FileToolError("INVALID_GLOB", "Use a relative POSIX glob without traversal")
    parts, glob = PurePosixPath(path).parts, tuple(pattern.split('/'))
    @lru_cache(None)
    def match(i, j):
        if j == len(glob):
            return i == len(parts)
        if glob[j] == '**':
            return match(i,j+1) or (i<len(parts) and match(i+1,j))
        return i<len(parts) and fnmatchcase(parts[i],glob[j]) and match(i+1,j+1)
    return match(0,0)


def candidates(files, glob):
    # Validate even when the source inventory is empty.
    matches_glob('validation',glob)
    return [path for path in sorted(files.available_paths)
        if files.can_read(path) and matches_glob(path,glob)]


def bounds(offset, limit):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise FileToolError("INVALID_SEARCH_BOUNDS", "offset >= 0 and 1 <= limit <= 100 are required")


def list_files(files, glob="**/*", offset=0, limit=30):
    bounds(offset,limit)
    paths = candidates(files,glob)
    chosen = paths[offset:offset+limit]
    return {"glob":glob, "paths":chosen, "total":len(paths), "offset":offset,
        "next_offset":offset+limit if offset+limit<len(paths) else None}


def search_files(files, query, glob="**/*", offset=0, limit=20, context=2):
    bounds(offset,limit)
    if not isinstance(query,str) or not query.strip() or len(query)>256:
        raise FileToolError("INVALID_SEARCH_QUERY", "Use a nonempty literal query of at most 256 characters")
    if type(context) is not int or not 0 <= context <= 5:
        raise FileToolError("INVALID_SEARCH_CONTEXT", "Use 0 <= context <= 5")
    paths = candidates(files,glob)
    matches, skipped, seen = [], [], 0
    scanned_bytes, excerpt_chars = 0, 0
    def finish(next_offset, truncated=False):
        return {"query":query,"glob":glob,"matches":matches,"offset":offset,
            "next_offset":next_offset,"scan_truncated":truncated or len(paths)>2000,
            "skipped_files":skipped[:20]}
    for relative in paths[:2000]:
        try:
            path = files.path(relative)
            if not path.is_file() or path.stat().st_size>1_000_000:
                skipped.append(relative)
                continue
            scanned_bytes += path.stat().st_size
            if scanned_bytes > 8_000_000:
                return finish(None,True)
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except (OSError,UnicodeError,FileToolError):
            skipped.append(relative)
            continue
        for number,line in enumerate(lines):
            if query.casefold() not in line.casefold():
                continue
            seen += 1
            if seen <= offset:
                continue
            if len(matches) == limit:
                return finish(offset+len(matches))
            excerpt = [{"line_number":i+1,"text":lines[i][:500],"text_truncated":len(lines[i])>500}
                for i in range(max(0,number-context),min(len(lines),number+context+1))]
            size = sum(len(row["text"]) for row in excerpt)
            if matches and excerpt_chars+size>16_000:
                return finish(offset+len(matches))
            excerpt_chars += size
            matches.append({"path":relative,"line_number":number+1,"context":excerpt})
    return finish(None)
