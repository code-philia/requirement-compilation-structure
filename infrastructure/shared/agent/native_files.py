"""Native file-tool documentation and feedback, without the legacy JSON envelope."""

from copy import deepcopy
from infrastructure.shared.agent.tools import FileToolError
from infrastructure.utils.files import read_source


DESCRIPTIONS = {
    'read_file': 'Read a specific authorized file only for a named missing definition. Reuse supplied file contents. '
        'Arguments: path, optional start_line/end_line (inclusive). Default 400 lines for backend/frontend/UI, maximum 2000. '
        'Batch independent native read_file calls in one response. Directories require list_files.',
    'list_files': 'Discover authorized filenames for a concrete missing owner. Arguments are optional glob, offset, limit. '
        'Use narrow globs and next_offset for pagination; a listing is not permission to edit. Do not list the whole project repeatedly.',
    'search_files': 'Literal, case-insensitive text search in authorized files. Supply query and preferably a narrow glob; '
        'optional offset/limit/context control results. Not regex or shell. Read only missing declarations at returned paths/lines.',
    'edit_file': 'Create or locally edit ONE authorized file. REQUIRED arguments: path, operation, new_content. '
        'operation=create ONLY when exists=false (omit old_content). For exists=true use replace with a unique exact old_content '
        'copied from supplied/read source, or append/prepend with new_content only. A compiler-provided empty registrar already '
        'exists: modify its current stub, never create it again. The tool does not rename/move files; new_path is unsupported. '
        'Preserve unrelated callers and source. Native arguments contain these fields directly, without tool/arguments/changes wrappers. '
        'Example for existing code: {"path":"backend/src/service.ts","operation":"replace",'
        '"old_content":"exact existing span","new_content":"replacement span"}. '
        'Example for a new file: {"path":"backend/src/new-service.ts","operation":"create","new_content":"source"}.',
    'bash': 'Run a focused bounded diagnostic in the authorized disposable snapshot. Provide command and optional timeout_seconds. '
        'No network or inherited provider keys. Writes are discarded: publish source changes using edit_file. '
        'Do not install dependencies, start persistent servers or rerun entire suites; the host owns acceptance.',
}


def native_file_definition(schema):
    name = schema['tool']
    parameters = deepcopy(schema['parameters'])
    parameters['properties'].pop('tool',None)
    parameters['required'] = [key for key in parameters['required'] if key != 'tool']
    for key, description in {
        'path':'Exact project-relative filename; consult provided exists/content state, not a directory or guessed new_path.',
        'operation':'Required. create for a missing file; replace/append/prepend for an existing file.',
        'new_content':'Required literal new source, replacement text, or appended/prepended text, not a patch envelope.',
        'old_content':'For replace only: one unique exact span from the current file. Omit for create/append/prepend.',
    }.items():
        if key in parameters['properties']:
            parameters['properties'][key]['description'] = description
    return DESCRIPTIONS.get(name,schema['description']), parameters


def native_file_feedback(files, name, arguments, feedback):
    value = deepcopy(feedback)
    example = value.pop('example',None)
    if isinstance(example,dict):
        example.pop('tool',None)
        value['example_arguments'] = example
    if 'tool' in value:
        value['tool_name'] = value.pop('tool')
    if value.get('code') == 'INVALID_CALL':
        value['message'] = 'Invalid native ' + name + ' arguments. Use exactly its advertised parameter names.'
    value['argument_format'] = 'Native function arguments only; do not add tool, arguments, tool_calls or changes wrappers.'
    if 'new_path' in value.get('unexpected_fields',[]):
        value['rename_not_supported'] = 'new_path is unsupported. This tool creates/edits path; it does not move or rename files.'
    path = arguments.get('path')
    if isinstance(path,str):
        try:
            target = files.path(path)
            if files.can_read(path):
                exists = target.is_file()
                state = {'path':path,'exists':exists,'writable':files.can_write(path)}
                if exists:
                    content = read_source(target)
                    lines = content.splitlines(keepends=True)
                    excerpt = ''.join(lines[:40])[:2500]
                    state.update(total_lines=len(lines), current_excerpt=excerpt,
                        excerpt_is_full_file=excerpt == content)
                value['file_state'] = state
                if name == 'edit_file':
                    if not state['writable']:
                        value.pop('example_arguments',None)
                        value['next_action'] = 'This path is read-only. Use the task-provided editable owner; do not retry writes here.'
                        return value
                    operation = ('append' if state.get('excerpt_is_full_file') and not state.get('current_excerpt') else 'replace') if exists else 'create'
                    value['suggested_operation'] = operation
                    example = {'path':path,'operation':operation,'new_content':'replacement source' if exists else 'new source'}
                    if exists and operation == 'replace':
                        example['old_content'] = state['current_excerpt'] if state['excerpt_is_full_file'] else 'one unique exact local span from current source'
                        if value.get('code') == 'WHOLE_FILE_REPLACEMENT_NOT_ALLOWED':
                            span = next((span for span in value.get('suggested_spans',[]) if span.get('old_content')),None)
                            example['old_content'] = span['old_content'] if span else 'one unique exact local span from current source'
                            if span:
                                example['new_content'] = span['new_content']
                    value['example_arguments'] = example
        except (FileToolError,OSError,UnicodeError):
            pass
    return value


def execute_native_file(files, name, arguments):
    try:
        results = files.execute([{'tool':name,**arguments}])
    except FileToolError as error:
        return {'status':'NEEDS_REPAIR','feedback':native_file_feedback(files,name,arguments,error.feedback)}
    # Read tools report per-call failures rather than throwing. Normalize these too.
    for item in results:
        if isinstance(item.get('error'),dict):
            item['error'] = native_file_feedback(files,name,arguments,item['error'])
        result = item.get('result')
        if name == 'read_file' and isinstance(result,dict) and isinstance(result.get('content'),str):
            excerpts = files.read_files.setdefault(result['path'],[])
            excerpts.append({key:result[key] for key in ('start_line','end_line','total_lines','content')})
            del excerpts[:-12]
        if isinstance(result,dict) and result.get('cached'):
            result['context_reference'] = 'Prior supplied file or native tool result in this retained conversation: ' + str(result.get('context_reference',''))
    return results
