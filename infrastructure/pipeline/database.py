"""Stage 04: lower the completed schema to SQL, seed explicit data and initialize."""

import hashlib
import json
from pathlib import Path

from infrastructure.stages.database.order import implementation_groups, table_dependencies
from infrastructure.stages.database.runtime import initializer_source
from infrastructure.stages.database.file_agent import DatabaseImplementationAgent
from infrastructure.stages.backend.platform_files import wire_initializer
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.tasks import TaskFailures
from infrastructure.utils.files import read_source, save_json, save_text
from infrastructure.shared.project.git import checkpoint
from infrastructure.stages.database.implementation import implement_startup_data, verify_database_runtime


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


def _implement_db_attempt(arc_dir: Path, pause=False, max_attempts=10, max_turns=10, model=None):
    schema_path = arc_dir / 'db_schema.json'
    if not schema_path.is_file():
        raise ValueError('Run 02_build_db_schema and 03_infer_db_obligations before SQL implementation')
    output = arc_dir.parent.resolve()
    schema = json.loads(read_source(schema_path))
    console = DemoConsole(pause)
    dependencies = table_dependencies(schema)
    batches = table_batches(schema)
    order = [name for batch in batches for name in batch]
    paths = {name: f'backend/src/db/tables/{name}.sql' for name in order}
    report_path = arc_dir / 'db_implementations.json'
    previous = json.loads(read_source(report_path)) if report_path.is_file() else {}
    report = {'status': 'IMPLEMENTING', 'schema_sha256': signature(schema['entities']),
        'order': order, 'tables': {}, 'batches': []}
    failures = TaskFailures(arc_dir, '04_implement_db', console)
    model = model or TextModel(json_mode=False)
    for index, names in enumerate(batches, 1):
        label = f'batch {index}/{len(batches)}: ' + ', '.join(names)
        entry = {'tables': names, 'status': 'RUNNING'}
        report['batches'].append(entry)
        with failures.task(label):
            referenced = set().union(*(set(dependencies[name]) for name in names)) - set(names)
            definitions = {name: schema['entities'][name] for name in names}
            # Only referenced key definitions can affect this batch's FK contract;
            # an unrelated password/role column in the target need not regenerate it.
            reference_keys = {}
            for entity in definitions.values():
                for field in entity['fields'].values():
                    if field.get('references'):
                        target,key = field['references'].split('.',1)
                        if target in referenced:
                            reference_keys.setdefault(target,{})[key] = schema['entities'][target]['fields'][key]
            inputs = signature({'tables': definitions,'reference_keys':reference_keys})
            reused = all(previous.get('tables', {}).get(name, {}).get('input_sha256') == inputs
                and (output / paths[name]).is_file()
                and previous['tables'][name].get('sql_sha256') == signature(read_source(output / paths[name]))
                for name in names)
            if reused:
                console.show('Database SQL | Reuse', label)
            else:
                requirements = [rid for rid, fields in schema.get('requirements', {}).items()
                    if any(symbol.split('.', 1)[0] in names for symbol in fields)]
                files = FileTools(output, ['backend/src/db/tables'], requirements=requirements,
                    stage='database', files=[paths[name] for name in [*names, *sorted(referenced)]],
                    writable=[paths[name] for name in names], readable=list(paths.values()))
                task = {'tables': definitions, 'output_paths': {name: paths[name] for name in names},
                    'referenced_tables': {name: schema['entities'][name] for name in referenced},
                    'dependency_order': names,
                    'schema_decisions': [decision for decision in schema.get('decisions', []) if decision.get('entity') in names]}
                DatabaseImplementationAgent('tables', INSTRUCTIONS, files,
                    lambda: inspect_ddl(output, schema, names), model=model).run(
                        task, max_turns=max_attempts, console=console, label=label)
            entry['status'] = 'GREEN'
            for name in names:
                report['tables'][name] = {'path': paths[name], 'status': 'GREEN',
                    'input_sha256': inputs, 'sql_sha256': signature(read_source(output / paths[name]))}
            checkpoint(output, stage='04', task=label, action='Publish schema SQL batch', status='GREEN')
        if failures.report['tasks'][label]['status'] == 'FAILED':
            entry.update(failures.report['tasks'][label])
        save_json(report_path, report)

    # Every expected table stays in the loader even after a failed first generation,
    # so final repair can create it instead of accidentally declaring partial success.
    initializer = output / 'backend/src/db/initialize.ts'
    save_text(initializer, initializer_source({name: {'path': paths[name]} for name in order}))
    if (output / 'backend/src/platform/bootstrap.ts').is_file():
        wire_initializer(initializer)
    checkpoint(output, stage='04', task='database initializer', action='Publish complete SQL loading order')
    implement_startup_data(arc_dir, schema, model, console, failures, max_attempts)
    with failures.task('database runtime'):
        report['verification'] = verify_database_runtime(arc_dir, schema, model, console, max_turns)
        # The integration agent may repair earlier SQL or seed publication failures.
        for label, outcome in list(failures.report['tasks'].items()):
            if outcome['status'] == 'FAILED':
                failures.report['tasks'][label] = {'status': 'GREEN', 'recovered_by': 'database runtime repair', 'initial_failure': outcome}
        for entry in report['batches']:
            if entry['status'] == 'FAILED':
                entry.update(status='GREEN', recovered_by='database runtime repair')
        for name in order:
            report['tables'].setdefault(name, {'path': paths[name]})
            report['tables'][name].update(status='GREEN', sql_sha256=signature(read_source(output / paths[name])))
    report['status'] = 'COMPLETED_WITH_FAILURES' if any(item['status'] == 'FAILED'
        for item in failures.report['tasks'].values()) else 'GREEN'
    report['tasks'] = failures.report['tasks']
    save_json(report_path, report)
    failures.finish()
    return report


def implement_db(arc_dir: Path, pause=False, max_attempts=10, max_turns=10):
    """Bounded design/DDL/INSERT feedback cycle; unchanged SQL batches are reused."""
    from infrastructure.stages.database.startup import reconcile_startup_schema, SchemaRepairRequested
    if not (arc_dir/'db_schema.json').is_file():
        raise ValueError('Complete database schema and obligations before SQL implementation')
    console, model = DemoConsole(pause), TextModel(json_mode=False)
    repairs, request = [], None
    for cycle in range(3):
        schema = json.loads(read_source(arc_dir/'db_schema.json'))
        try:
            repair = reconcile_startup_schema(arc_dir,schema,model=model,console=console,
                request=request,max_turns=max(24,max_turns))
        except (ValueError,RuntimeError) as error:
            save_json(arc_dir/'db_schema_repairs.json',{'status':'FAILED','cycles':repairs,
                'pending_request':request,'error':str(error)})
            raise
        repairs.append(repair)
        save_json(arc_dir/'db_schema_repairs.json',{'status':'RUNNING','cycles':repairs})
        try:
            report = _implement_db_attempt(arc_dir,pause,max_attempts,max_turns,model=model)
            report['schema_reconciliation'] = repairs
            save_json(arc_dir/'db_implementations.json',report)
            save_json(arc_dir/'db_schema_repairs.json',{'status':report['status'],'cycles':repairs})
            return report
        except SchemaRepairRequested as error:
            request = error.request
            console.show('Database | Reconcile schema before resuming SQL',
                request['reason']+'\nAffected DDL is relowered; unchanged batches stay reusable. Source records are retained.')
    save_json(arc_dir/'db_schema_repairs.json',{'status':'FAILED','cycles':repairs,'pending_request':request})
    if (arc_dir/'db_implementations.json').is_file():
        report = json.loads(read_source(arc_dir/'db_implementations.json'))
        report.update(status='FAILED',schema_reconciliation=repairs,pending_schema_repair=request)
        save_json(arc_dir/'db_implementations.json',report)
    raise RuntimeError('Database source/schema contradiction remains after bounded reconciliation; see .arc/db_schema_repairs.json')
