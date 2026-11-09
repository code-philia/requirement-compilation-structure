"""Agent-produced seed SQL with source coverage and executable row evidence."""

import json
import uuid

MANIFEST = "backend/src/db/seed-evidence.json"

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
Source test accounts are bootstrapped by the identity platform, not by this task.
Keep platform identity, policy, sessions and audit tables unchanged. Ownership may be
established only from explicit source unit/owner evidence; never grant extra memberships.

Edit per-table backend/src/db/seeds/TABLE.sql files. Each inserts only into its own table.
Use idempotent INSERT ... SELECT ... WHERE NOT EXISTS or targeted ON CONFLICT;
never INSERT OR IGNORE, DELETE, DROP, REPLACE, schema changes or disabling foreign keys.
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
Include exactly all supplied business SEED IDs and all their original property names.
Rows are observable expectations for the SQL you implement, not an alternative to INSERTs.
Each locator must contain a primary/unique key (including all columns of a composite key).
Include related rows needed to preserve foreign-key display names. Property mappings refer
to a rows index and a field whose value equals the source value (numeric text is allowed). For a source {$ref: DATA-ID},
map to the actual FK field and resolved target key; account IDs are in identity_references.
Canonical bound fields supplied in task.catalog remain requirements; reuse their technical
IDs. Every rows entry is checked after real initialization and repeated startup.
If evidence is truly contradictory, report the conflict explicitly; do not invent a
success, silently skip data or weaken a source value to pass a check.
'''


def sql_value(value):
    return int(value) if isinstance(value, bool) else json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value


def seed_assertions(output, schema, catalog):
    """Validate full source coverage; return row checks for the real DB startup gate."""
    seeds = {rid: row for rid, row in catalog['records'].items()
        if row['lifecycle'] == 'SEED' and row['entity'] != 'test account'}
    if not seeds:
        return []
    path = output / MANIFEST
    if not path.is_file():
        raise ValueError('Seed SQL requires its source coverage manifest: ' + MANIFEST)
    evidence = json.loads(path.read_text(encoding='utf-8-sig'))
    for key in ('source_sha256', 'schema_sha256'):
        if evidence.get(key) != catalog[key]:
            raise ValueError('Seed evidence is stale: ' + key)
    if set(evidence.get('records', {})) != set(seeds):
        raise ValueError('Seed evidence must cover exactly every explicit business SEED record')
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
        for name, value in source.get('properties', {}).items():
            mapping = properties[name]
            if mapping.get('display_only') is True:
                if not mapping.get('reason'):
                    raise ValueError(rid + ': display-only properties need evidence')
                continue
            index, field = mapping.get('row'), mapping.get('field')
            if type(index) is not int or not 0 <= index < len(rows) or field not in rows[index]['fields']:
                raise ValueError(rid + ': invalid source property mapping: ' + name)
            stored = rows[index]['fields'][field]
            if isinstance(value, dict) and "$ref" in value:
                target = catalog['records'].get(value['$ref'])
                reference = schema['entities'][rows[index]['entity']]['fields'][field].get('references')
                if not target or target['lifecycle'] != 'SEED' or not reference:
                    raise ValueError(rid + ': seed reference needs a published SEED target and schema FK')
                target_entity, target_field = reference.split('.')
                if target['entity'] == 'test account':
                    expected = str(uuid.uuid5(uuid.NAMESPACE_URL, 'arc-backend:user:' + target['properties']['username']))
                    matches = target_entity == 'users' and target_field == 'id' and stored == expected
                else:
                    target_rows = evidence['records'][value['$ref']]['rows']
                    matches = any(r['entity'] == target_entity and
                        {**r['locator'], **r['fields']}.get(target_field) == stored for r in target_rows)
                if not matches:
                    raise ValueError(rid + ': reference does not resolve to the source target row')
                persisted += 1
                continue
            # FK labels map to related-row fields, never to invented opaque IDs.
            if stored != value and not (isinstance(stored, (str, int, float)) and isinstance(value, (str, int, float)) and str(stored) == str(value)):
                raise ValueError(rid + ': preserve the source value for ' + name)
            persisted += 1
        if source.get('properties') and not persisted:
            raise ValueError(rid + ': cannot classify an entire business record as decoration')
    return result
