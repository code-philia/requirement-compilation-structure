"""Author fake model tool responses for orchestration tests; no production compatibility layer."""

from infrastructure.utils.files import read_source


def propose_files(output, contents, **extra):
    if contents is None:
        return {**extra, 'tool_calls': None}
    staged, calls = {}, []
    for item in contents:
        path, content = item['path'], item['content']
        file = output / path
        before = item.get('old_content', staged.get(path, read_source(file) if file.resolve().is_relative_to(output.resolve()) and file.is_file() else None))
        arguments = {'path': path, 'operation': 'create' if before is None else 'replace', 'new_content': content}
        if before is not None:
            arguments['old_content'] = before
        calls.append({'tool': 'edit_file', 'arguments': arguments})
        staged[path] = content
    return {**extra, 'tool_calls': calls}
