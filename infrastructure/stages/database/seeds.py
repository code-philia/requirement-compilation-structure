"""Agent-produced seed SQL with source coverage and executable row evidence."""

import json

MANIFEST = "backend/src/db/seed-evidence.json"


class SeedBindingError(ValueError):
    def __init__(self, record, prop, row, field, rows, schema):
        super().__init__(record+': invalid source property mapping: '+prop)
        entity = rows[row].get('entity') if type(row) is int and 0<=row<len(rows) else None
        self.feedback = {'record':record,'property':prop,'row':row,'field':field,'entity':entity,
            'valid_row_indices':list(range(len(rows))),
            'available_fields':list(schema['entities'].get(entity,{}).get('fields',{})),
            'next_action':'Correct a mistaken evidence row/field if the schema supports this source property. '
                'If it cannot, request_schema_repair with source IDs; do not invent fields or omit source facts.'}

SEED_RULES = '''Implement startup INSERT SQL from the source data records AFTER reading the actual
CREATE TABLE files. Source entity names and properties may be UI labels (e.g. a document
record, warehouse display name, quantity or amount), not canonical SQL identifiers.
Resolve their meaning from requirement prose, ER relationships and actual DDL. Do not
reject a record merely because an entity/column string does not match the schema.
A source record may need several rows: header, detail, related warehouse/product/SKU.
Resolve named references by existing business keys or create the minimum parent rows
needed by explicit SEED records. Reuse shared parents across records. Preserve exact
source business numbers, amounts, status and labels; do not turn displayed totals into
unrelated fields. Number decimals must remain exact text where the DDL requires it.
For missing mandatory technical fields choose deterministic values and record the
assumption. Do not invent approvals, business history, permissions or tenant membership.
Use the actual requirements to distinguish list decoration from persistent facts.
A row number or rendered action list can be display-only, with an explicit reason;
never silently drop a source record or meaningful business property.

Only lifecycle=SEED records belong in startup SQL. CREATED/DERIVED records and scenario
When/Then outcomes must not be inserted. Given clauses help interpret explicit data,
not a license to materialize every hypothetical scenario prerequisite at application start.
Explicit source account records are part of this task too: resolve their tables,
credential columns and memberships from the ACTUAL schema. There is no preset users,
roles, organizations table, account UUID formula, administrator or default password.
Only create source-required rows/memberships, never fabricate sessions or extra grants.
If a credential is stored as a password hash, use seed_password_hash('source password');
it produces scrypt$saltHex$digestHex. Record a property binding with transform=password_hash
instead of putting plaintext or a random generated hash in expected row fields.

Edit per-table backend/src/db/seeds/TABLE.sql files. Each inserts only into its own table.
If a table SQL file contradicts the canonical definitions (for example an invented CHECK
excluding valid source roles), repair that DDL to match the supplied schema. Never add
unmodeled columns or weaken legitimate constraints. If the LOGICAL schema itself is
incomplete, use request_schema_repair rather than editing around its missing fields.
Use idempotent INSERT ... SELECT ... WHERE NOT EXISTS or targeted ON CONFLICT;
never INSERT OR IGNORE, DELETE, DROP, REPLACE, unapproved schema changes or disabling foreign keys.
The loader runs in dependency order within a transaction, with deferred FK checks.
Use stable record identities, preserve existing records on repeat startup, and avoid
copying SQL into seed.ts or DDL. Use edit_file for SQL and the evidence manifest.

Also write task.manifest_path as JSON:
{
 "source_sha256": "supplied source hash", "schema_sha256": "supplied schema hash",
 "records": {
   "DATA-ID": {
     "reason": "evidence for entity/relationship interpretation",
     "assumptions": ["minimal missing-field choices, if any"],
     "rows": [{"entity":"canonical_table", "locator":{"business_key":"value"},
               "fields":{"business_key":"value","name":"source label"}}],
     "properties": {
       "source property name": {"row":0,"field":"name"},
       "source display-only property": {"display_only":true,"reason":"why it is presentation only"}
     }
   }
 }
}
Include exactly all supplied SEED IDs and all their original property names.
Rows are observable expectations for the SQL you implement, not an alternative to INSERTs.
Each locator must contain a primary/unique key (including all columns of a composite key).
Include related rows needed to preserve foreign-key display names. Property mappings refer
to a rows index and a field whose value equals the source value (numeric text is allowed). For a source {$ref: DATA-ID},
map to the actual FK field and resolved target key in that source record's manifest rows.
For a nested property mapped to several relational rows, use
{"bindings":[{"row":0,"field":"role_code","source_path":[0,"role"]}, ...]}.
Paths are relative to the property value and must cover every leaf value exactly or as
an entire JSON subtree; map unit/role labels to actual related-row code/name fields.
For hashed credentials use {"row":0,"field":"credential_column","transform":"password_hash"};
the field must exist in the schema but should be omitted from row.fields because its
salted value is generated at startup. Runtime checks verify it against the source password.
Canonical bound fields supplied in task.catalog remain requirements; reuse their technical
IDs. Every rows entry is checked after real initialization and repeated startup.
If evidence is truly contradictory, report the conflict explicitly; do not invent a
success, silently skip data or weaken a source value to pass a check.
'''


def source_seed_records(catalog):
    """All explicit source seeds, including accounts with noncanonical table labels."""
    return {rid: row for rid, row in catalog.get('records', {}).items() if row['lifecycle'] == 'SEED'}


def leaf_paths(value):
    if isinstance(value, dict) and '$ref' not in value and value:
        return {(key,) + suffix for key, child in value.items() for suffix in leaf_paths(child)}
    if isinstance(value, list) and value:
        return {(index,) + suffix for index, child in enumerate(value) for suffix in leaf_paths(child)}
    return {()}


def sql_value(value):
    return int(value) if isinstance(value, bool) else json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value


def seed_assertions(output, schema, catalog, record_ids=None):
    """Validate full source coverage; return row checks for the real DB startup gate."""
    all_seeds = source_seed_records(catalog)
    seeds = all_seeds if record_ids is None else {key:all_seeds[key] for key in record_ids}
    if not seeds:
        return []
    path = output / MANIFEST
    if not path.is_file():
        raise ValueError('Seed SQL requires its source coverage manifest: ' + MANIFEST)
    evidence = json.loads(path.read_text(encoding='utf-8-sig'))
    for key in ('source_sha256', 'schema_sha256'):
        if evidence.get(key) != catalog[key]:
            raise ValueError('Seed evidence is stale: ' + key)
    evidence_ids = set(evidence.get('records',{}))
    if (record_ids is None and evidence_ids!=set(seeds)) or not set(seeds)<=evidence_ids or evidence_ids-set(all_seeds):
        raise ValueError('Seed evidence must cover exactly every explicit SEED record')
    result = []
    for rid, source in seeds.items():
        resolution = evidence['records'][rid]
        if not resolution.get('reason') or not isinstance(resolution.get('assumptions'), list):
            raise ValueError(rid + ': explain seed interpretation and missing-field assumptions')
        rows = resolution.get('rows')
        if not isinstance(rows, list) or not rows:
            raise ValueError(rid + ': source record cannot be silently omitted')
        for index, row in enumerate(rows):
            entity = schema['entities'].get(row.get('entity'))
            locator, fields = row.get('locator'), row.get('fields')
            if not entity or not isinstance(locator, dict) or not locator or not isinstance(fields, dict):
                raise ValueError(rid + ': use a canonical entity and explicit locator/fields')
            if set(locator) - set(entity['fields']) or set(fields) - set(entity['fields']):
                raise ValueError(rid + ': unknown seed observation fields')
            primary = {name for name, definition in entity['fields'].items() if definition['primary_key']}
            keys = ([primary] if primary else []) + [{name} for name, definition in entity['fields'].items() if definition['unique']]
            keys += [set(key) for key in entity.get('unique_constraints', [])]
            if not any(key and key <= set(locator) for key in keys) or any(v is None for v in locator.values()):
                raise ValueError(rid + ': seed locator must contain a complete non-null unique key')
            if any(key in fields and fields[key] != value for key, value in locator.items()):
                raise ValueError(rid + ': conflicting locator and expected field value')
            result.append({'id': f'{rid}/{index}', 'entity': row['entity'], 'locator': {k: sql_value(v) for k, v in locator.items()},
                'lifecycle': 'SEED', 'fields': {k: sql_value(v) for k, v in {**locator, **fields}.items()}})
        properties = resolution.get('properties', {})
        if set(properties) != set(source.get('properties', {})):
            raise ValueError(rid + ': explain every original source property')
        persisted = 0
        checks = result[-len(rows):]
        for name, value in source.get('properties', {}).items():
            mapping = properties[name]
            if mapping.get('display_only') is True:
                if not mapping.get('reason'):
                    raise ValueError(rid + ': display-only properties need evidence')
                if source.get('entity') == 'test account':
                    raise ValueError(rid + ': account credentials/memberships are not display decoration')
                continue
            bindings = mapping.get('bindings')
            if bindings is None:
                bindings = [mapping]
            if not isinstance(bindings, list) or not bindings:
                raise ValueError(rid + ': supply property bindings for ' + name)
            covered = set()
            for binding in bindings:
                path = binding.get('source_path', [])
                if not isinstance(path, list):
                    raise ValueError(rid + ': source_path must be an array')
                selected = value
                for key in path:
                    selected = selected[key]
                index, field = binding.get('row'), binding.get('field')
                if (type(index) is not int or not 0 <= index < len(rows)
                        or not isinstance(field,str) or field not in schema['entities'][rows[index]['entity']]['fields']):
                    raise SeedBindingError(rid,name,index,field,rows,schema)
                if source.get('entity')=='test account' and name=='password' and binding.get('transform')!='password_hash':
                    raise ValueError(rid+': source account password requires transform=password_hash and seed_password_hash SQL, not plaintext storage')
                if binding.get('transform') == 'password_hash':
                    if not isinstance(selected, str) or field in rows[index]['fields']:
                        raise ValueError(rid + ': omit generated hash from fields; source password must be text')
                    checks[index].setdefault('password_hashes', {})[field] = selected
                else:
                    if binding.get('transform'):
                        raise ValueError(rid + ': unsupported property transform')
                    if field not in rows[index]['fields']:
                        raise ValueError(rid + ': mapped field must have an expected source value')
                    stored = rows[index]['fields'][field]
                    if isinstance(selected, dict) and '$ref' in selected:
                        target = catalog['records'].get(selected['$ref'])
                        reference = schema['entities'][rows[index]['entity']]['fields'][field].get('references')
                        if not target or target['lifecycle'] != 'SEED' or not reference:
                            raise ValueError(rid + ': seed reference needs a SEED target and schema FK')
                        target_entity, target_field = reference.split('.')
                        target_rows = evidence['records'][selected['$ref']]['rows']
                        if not any(r['entity'] == target_entity and
                                {**r['locator'], **r['fields']}.get(target_field) == stored for r in target_rows):
                            raise ValueError(rid + ': reference does not resolve to source target row')
                    elif stored != selected and not (isinstance(stored, (str, int, float))
                            and isinstance(selected, (str, int, float)) and str(stored) == str(selected)):
                        raise ValueError(rid + ': preserve the source value for ' + name)
                covered.update(tuple(path) + leaf for leaf in leaf_paths(selected))
            if covered != leaf_paths(value):
                raise ValueError(rid + ': bindings must preserve every nested source value in ' + name)
            persisted += 1
        if source.get('properties') and not persisted:
            raise ValueError(rid + ': cannot classify an entire source record as decoration')
    return result
