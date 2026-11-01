"""Explicit obligation records and resolvable database symbols."""


def normalize_record(record):
    if not isinstance(record, dict):
        raise ValueError('An obligation record must explicitly contain read and write arrays')
    result = {}
    for mode in ('read', 'write'):
        values = record[mode]
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError(f'{mode} must be an array of qualified DB field strings')
        result[mode] = sorted(set(values))
    return result


def normalize_inference(result, step_ids):
    return {'requirement': normalize_record(result['requirement']),
        'steps': {sid: normalize_record(result['steps'][sid]) for sid in step_ids}}


def normalize_obligations(value, tree):
    return {kind: {key: normalize_record(value[kind][key]) for key in expected}
        for kind, expected in (('requirements', tree.requirements), ('steps', tree.steps))}


def check_symbols(records, schema):
    """Validate declared fields, without claiming that code implements these effects."""
    from infrastructure.stages.database.schema import check_related_fields
    for record in records:
        normalized = normalize_record(record)
        check_related_fields(schema, normalized['read'] + normalized['write'])
