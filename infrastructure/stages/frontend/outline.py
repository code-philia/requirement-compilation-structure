"""Tolerant UI coordination metadata; never interpret prose as a filesystem path."""

from copy import deepcopy
import re

from infrastructure.shared.agent.files import editable_application_path
from infrastructure.utils.paths import relative_path


DESIGN_EXAMPLE = {'items':{'page-example':{'purpose':'Source-required page and its main actions',
    'kind':'page','route':'/source-route','implementation_hint':'frontend/src/pages/ExamplePage.tsx','api_ids':[]}},
    'uses':['page-example'],'notes':'Reuse the actual shared shell/client. Descriptions belong here or in purpose, never in a path.'}


class OutlineError(ValueError):
    def __init__(self, problems):
        super().__init__('UI outline needs a local format correction; successful earlier calls remain saved')
        self.feedback = {'problems':problems,'example_arguments':deepcopy(DESIGN_EXAMPLE),
            'instruction':'items maps stable UI IDs to records (or use a list of records with id). '
                'uses contains those IDs, not Arco names or filenames. implementation_hint is ONE filename only. '
                'Return one minimal corrected item, then extend it; do not regenerate unrelated designs.'}


def implementation_path(value, output):
    """Strip clear annotations after a single complete source filename, preserving safe paths."""
    if not isinstance(value,str):
        raise ValueError('implementation_hint must be one source filename')
    value = value.strip().strip('`')
    match = re.match(r'^(frontend/src/[^\r\n]*?\.(?:tsx?|jsx?|css|scss|json))(?=$|[\s:：—–(（])',value)
    if not match:
        raise ValueError('Use a frontend/src/ filename with its extension; put responsibility text in purpose')
    path, annotation = match.group(1), value[match.end():].strip()
    if annotation and (re.search(r'(?:frontend/|\.(?:tsx?|jsx?|css)\b)',annotation) or annotation.startswith(('+','/','\\'))):
        raise ValueError('Multiple/ambiguous file locations: split responsibilities into separate UI items')
    parts = relative_path(path).parts
    if any(len(part.encode('utf-8'))>240 for part in parts):
        raise ValueError('Filename is too long; move descriptive prose into purpose')
    if not editable_application_path(output,path):
        raise ValueError('Choose an application-owned source file, not a compiler-owned provider/runtime')
    return path, annotation


def normalize_items(items, rid, output):
    if isinstance(items,dict) and isinstance(items.get('implementation_hint'),str):
        items = {str(items.get('id') or 'ui-'+rid):items}
    if isinstance(items,list):
        if any(not isinstance(item,dict) for item in items):
            raise OutlineError(['Every list item must be an object with purpose and implementation_hint'])
        items = {str(item.get('id') or 'ui-'+rid+'-'+str(i)):item for i,item in enumerate(items,1)}
    if not isinstance(items,dict):
        raise OutlineError(['items must be a map of UI IDs or a list of item records'])
    result, problems = {}, []
    for identity,item in items.items():
        if not isinstance(item,dict):
            problems.append({'id':str(identity),'error':'Expected a UI item object, not an individual field value'})
            continue
        record = deepcopy(item)
        try:
            path, annotation = implementation_path(record.get('implementation_hint'),output)
            record['implementation_hint'] = path
            if annotation:
                record['location_note'] = annotation
            if not isinstance(record.get('purpose'),str) or not record['purpose'].strip():
                raise ValueError('Supply a short source-based purpose')
            if 'route' in record and not isinstance(record['route'],str):
                raise ValueError('route must be a string when supplied; omit it for non-routed components')
            for field in ('api_ids','depends_on','states'):
                value = record.get(field,[])
                if isinstance(value,str):
                    value = [value]
                if not isinstance(value,list) or any(not isinstance(v,str) for v in value):
                    raise ValueError(field+' must contain string IDs/states')
                if field in record:
                    record[field] = list(dict.fromkeys(value))
            record.pop('id',None)
            result[str(identity)] = record
        except ValueError as error:
            problems.append({'id':str(identity),'error':str(error)})
    if problems:
        raise OutlineError(problems)
    return result


def normalize_plan_paths(plan, output):
    """Repair legacy annotations before reuse; keep unresolved metadata explicitly visible."""
    plan = deepcopy(plan)
    diagnostics = []
    for identity,item in plan.get('items',{}).items():
        if not isinstance(item,dict):
            plan['items'][identity] = {'purpose':str(item),'unresolved_design_record':True}
            diagnostics.append({'id':identity,'error':'Legacy item was not an object; preserve source text and refine its file location'})
            continue
        try:
            path, annotation = implementation_path(item.get('implementation_hint'),output)
            item['implementation_hint'] = path
            if annotation:
                item['location_note'] = annotation
        except (ValueError,TypeError,AttributeError) as error:
            diagnostics.append({'id':identity,'error':str(error)})
    plan['location_diagnostics'] = diagnostics
    return plan
