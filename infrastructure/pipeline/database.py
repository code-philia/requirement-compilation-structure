"""Lower the completed schema to SQL, seed explicit data and initialize."""

import hashlib
import json
from pathlib import Path

from infrastructure.stages.database.order import implementation_groups
from infrastructure.utils.files import read_source


INSTRUCTIONS = """Implement the supplied COMPLETE canonical db schema as SQLite DDL.
This is implementation, not another design pass. The task supplies a dependency-ordered
batch of tables and external FK target definitions. Implement ALL tables in this batch,
using each exact output_paths entry. Several native edit_file calls can be returned in
ONE response, followed by finish_implementation in that same response.

Create each table with CREATE TABLE IF NOT EXISTS; quote table and field identifiers.
Preserve exact names, types, keys, nullability, uniqueness, references and supported
constraints. Honor sqlite_type when present; otherwise string/uuid/date/datetime/json
map to TEXT, integer/boolean to INTEGER, number to REAL. Exact decimal text stays TEXT.
Multiple primary_key fields form ONE composite PRIMARY KEY. Use explicit NOT NULL for
nullable=false, including non-integer primary keys. Preserve entity.unique_constraints.
Do not invent defaults, normalization, cascades, business columns or preset identity
infrastructure. Any account/role/session table is just its actual supplied definition.

Implement enforceable scalar rules as CHECKs. SQLite CHECK cannot contain subqueries,
SELECT/EXISTS, aggregates or window functions. JSON validation uses scalar json_valid
and json_type; array-element, cross-row and application-only rules stay in application
code, with a short SQL comment explaining them. Forward FKs and cyclic groups are valid.
Never put INSERTs, application code, PRAGMA settings or transaction control in table SQL.
The host owns ordered loaders, transactions and foreign-key activation.

All relevant current SQL is supplied. Batch only missing reads. Use local replacements
when rerunning and preserve existing data. Do not touch schema artifacts or unrelated
application code. A local SQL execution failure is repair feedback, not a reason to
abandon the batch. finish_implementation checks the actual DDL in a disposable SQLite
connection; full application initialization follows after all batches and seed SQL.
"""


def signature(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def table_batches(schema, max_tables=6, max_fields=100):
    """Pack dependency components without splitting a cycle or assuming domain names."""
    result, batch, fields = [], [], 0
    for group in implementation_groups(schema):
        count = sum(len(schema['entities'][name]['fields']) for name in group)
        if batch and (len(batch) + len(group) > max_tables or fields + count > max_fields):
            result.append(batch)
            batch, fields = [], 0
        batch.extend(group)
        fields += count
    if batch:
        result.append(batch)
    return result


def inspect_ddl(output, schema, names):
    """Execute only DDL in memory to give the agent immediate, table-specific feedback."""
    import sqlite3
    connection = sqlite3.connect(':memory:')
    try:
        for name in names:
            relative = f'backend/src/db/tables/{name}.sql'
            path = output / relative
            if not path.is_file() or not read_source(path).strip():
                raise ValueError(f'Missing nonempty SQL file: {relative}')
            try:
                connection.executescript(read_source(path))
                quoted = '"' + name.replace('"', '""') + '"'
                columns = {row[1]: row for row in connection.execute(f'PRAGMA table_info({quoted})')}
                expected = schema['entities'][name]['fields']
                missing = sorted(set(expected) - set(columns))
                extra = sorted(set(columns) - set(expected))
                if missing or extra or not columns:
                    raise ValueError(f'{name}: columns differ from schema; missing={missing}, extra={extra}')
                for field, definition in expected.items():
                    row = columns[field]
                    if bool(row[5]) != bool(definition['primary_key']):
                        raise ValueError(f'{name}.{field}: primary key differs from schema')
            except (sqlite3.Error, ValueError) as error:
                raise ValueError(f'{relative}: {error}') from error
    finally:
        connection.close()
    return {'status': 'GENERATED', 'tables': names, 'check': 'DDL executed in memory'}



def implement_db(arc_dir, pause=False, max_attempts=10, max_turns=40):
    """Compatibility Python entry; the single SQL-first implementation is authoritative."""
    from infrastructure.pipeline.database_build import implement_database
    return implement_database(arc_dir, pause=pause, max_turns=max_turns)
