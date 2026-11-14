"""ER design -> SQL implementation/root data -> prose-driven SQL corrections."""

from copy import deepcopy
import hashlib
import json
import re

from infrastructure.shared.agent import AgentTool
from infrastructure.shared.agent.feedback import CheckFailure
from infrastructure.shared.agent.tasks import TaskFailures
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.models.text import TextModel
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.shared.project.git import checkpoint
from infrastructure.stages.database.design_agent import DatabaseDesignAgent
from infrastructure.stages.database.file_agent import DatabaseFileAgent
from infrastructure.stages.database.implementation import WIRING
from infrastructure.stages.database.runtime import initializer_source, seed_source
from infrastructure.stages.database.testing import DatabaseChecks
from infrastructure.utils.files import read_artifact, save_json, save_text
from infrastructure.utils.presentation.console import DemoConsole


RULES = """Implement and maintain the REAL application database using native tools.
Implementation task: request next_schema_batch, implement all supplied table DDL in
dependency order (batch independent edits), continue until batches are exhausted,
then call read_root_data and implement its startup data as per-table INSERT SQL.
One agent conversation owns that sequence. Do not traverse requirement nodes here.

Correction task: read the supplied requirement prose batch. Decide whether current
table definitions/DDL or startup INSERTs need additions or corrections, then edit
the actual responsible files. A no-change decision is valid. Do not generate a
separate design proposal, seed manifest, property mapping or read/write obligation.
Use description and scenarios as evidence: ordinary scenario-created records and
Given examples are not automatically startup presets. Never invent business rows.

During correction, derive necessary supporting persistence from functional prose even
when omitted from ER. Signed-in users/password change/logout require representable
accounts and credentials, revocable sessions, and source-defined roles/memberships.
Team isolation requires an unambiguous persisted account-to-team association AND a
persisted ownership path for each exposed resource (direct tenant key or justified FK
path). Add missing support entities/fields with upsert_entity and matching DDL/migrations
in this correction phase; do not defer them to API handlers. Choose names and shape from
the source, never a fixed application/role catalog. Current seed accounts may legitimately
share one team; preserve that data without making all future accounts share it. Business
rows without ownership need explicit source-backed initialization/migration, not a
reading-time adoption rule. Do not seed hypothetical scenario A/B data as production
records. Use read_root_data to inspect actual supplied accounts/memberships instead of
guessing them. Preserve source account credentials as hashes and declared memberships.

Use CREATE TABLE IF NOT EXISTS, actual keys/FKs/constraints, idempotent INSERTs and
dependency-ordered parent rows. Source record IDs are references, not automatically
persisted keys; resolve them to actual referenced rows. Preserve source values and
roles. Store source-required credentials with an appropriate hash, implementing or
reusing actual hashing/verification code. Do not assume an unadvertised helper exists.
If schema cannot represent supplied facts, use upsert_entity and immediately update
the corresponding SQL in this SAME loop. Logical metadata and SQL must stay in sync.
This is not a request to restart database design. Preserve unrelated schema/code/data.
Use local database migrations when needed; never drop user data or disable FKs.

SQL goes in backend/src/db/tables/<entity>.sql and db/seeds/<entity>.sql. The host
maintains ordered SQL loader lists; you may repair initialization/client/build wiring.
Do not change API/UI behavior. No seed-evidence.json or extra binding fields are needed.
finish_implementation executes real build, initialization and repeated-startup checks.
Use the error to repair the responsible files, not an imaginary metadata mapping.
After a repeated unchanged error, change repair strategy and inspect the exact cause;
if blocked, report that cause instead of repeating the same edit indefinitely.
"""


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def synchronize_loaders(arc_dir, schema):
    from infrastructure.pipeline.database import table_batches
    output = arc_dir.parent
    order = [name for batch in table_batches(schema) for name in batch]
    paths = {name: {'path': f'backend/src/db/tables/{name}.sql'} for name in order}
    for relative, rendered, variable in (
        ('backend/src/db/initialize.ts', initializer_source(paths), 'tableFiles'),
        ('backend/src/db/seed.ts', seed_source(order), 'seedFiles'),
    ):
        path = output / relative
        if path.is_file():
            current = path.read_text(encoding='utf-8-sig')
            pattern = rf'export const {variable}: readonly string\[\] = \[[\s\S]*?\];'
            replacement = re.search(pattern, rendered).group(0)
            if not re.search(pattern, current):
                raise ValueError(f'{relative}: preserve the {variable} SQL loader declaration')
            rendered = re.sub(pattern, lambda _: replacement, current, count=1)
        save_text(path, rendered)
    for name in order:
        path = output / f'backend/src/db/seeds/{name}.sql'
        if not path.is_file():
            save_text(path, '-- No startup rows required yet.\n')
    save_json(arc_dir / 'db_schema.json', schema)


class DatabaseBuildAgent(DatabaseFileAgent):
    """SQL writes and evidence-backed schema edits share one native tool loop."""

    repair_budget = 10

    def __init__(self, arc_dir, schema, raw, *, correction=False, **options):
        self.arc_dir, self.schema, self.raw = arc_dir, schema, raw
        self.correction, self.batch_index, self.root_read = correction, 0, correction
        from infrastructure.pipeline.database import table_batches
        self.batches = table_batches(schema)
        paths = set(WIRING) | {f'backend/src/db/{kind}/{name}.sql'
            for name in schema['entities'] for kind in ('tables', 'seeds')}
        paths -= {'backend/src/app.ts', 'backend/src/api/register.ts'}
        files = FileTools(arc_dir.parent, ['backend/src/db', 'backend/scripts', 'backend/src/server.ts',
            'package.json', 'backend/package.json', 'backend/tsconfig.json'],
            stage='database', files=sorted(paths), writable=paths, readable=paths)
        files.defer_context_files = True
        files.replaceable_files = {p for p in paths if p.endswith('.sql')}
        self.design = DatabaseDesignAgent(schema, {}, mode='implementation',
            persist=lambda: save_json(arc_dir / 'db_schema.json', schema))
        super().__init__(RULES, files, self.check_database, **options)

    def build_tools(self):
        tools = super().build_tools()
        for tool in self.design.build_tools():
            if tool.name == 'retrieve_entity':
                tools.append(tool)
            elif tool.name == 'upsert_entity':
                tools.append(AgentTool(tool.name, 'Repair logical metadata, then edit matching SQL in this loop.',
                    tool.parameters, self.upsert_entity))
        if not self.correction:
            tools.extend([
                AgentTool('next_schema_batch', 'Get the next dependency-ordered schema batch; implement it before requesting the next.',
                    {'type': 'object', 'properties': {}, 'additionalProperties': False}, self.next_schema_batch),
                AgentTool('read_root_data', 'Read the original root data after implementing all schema batches. No path or mappings required.',
                    {'type': 'object', 'properties': {}, 'additionalProperties': False}, self.read_root_data),
            ])
        else:
            tools.append(AgentTool('read_root_data','Read original account/role/team and other startup facts while correcting schema; do not invent seed values.',
                {'type':'object','properties':{},'additionalProperties':False},self.read_root_data))
        return tools

    def upsert_entity(self, **arguments):
        result = self.design.upsert_entity(**arguments)
        name = arguments['name']
        for kind in ('tables', 'seeds'):
            path = f'backend/src/db/{kind}/{name}.sql'
            self.files.files.add(path)
            self.files.readable.add(path)
            self.files.writable.add(path)
            self.files.replaceable_files.add(path)
        self.accepted = None
        self._turn_progress = not bool(result.get('unchanged')) or self._turn_progress
        return {**result, 'next_action': 'Update matching DDL/INSERTs before finish_implementation.'}

    def next_schema_batch(self):
        if self.batch_index >= len(self.batches):
            return {'status': 'ALL_BATCHES_SUPPLIED', 'next_action': 'read_root_data'}
        names = self.batches[self.batch_index]
        self.batch_index += 1
        return {'batch': self.batch_index, 'total': len(self.batches),
            'entities': {name: self.schema['entities'][name] for name in names},
            'output_paths': {name: f'backend/src/db/tables/{name}.sql' for name in names}}

    def read_root_data(self):
        if not self.correction and self.batch_index < len(self.batches):
            raise ValueError('Implement the remaining schema batches before reading root data')
        from infrastructure.pipeline.database import inspect_ddl, table_batches
        names = [name for batch in table_batches(self.schema) for name in batch]
        if not self.correction:
            inspect_ddl(self.arc_dir.parent, self.schema, names)
        self.root_read = True
        return {'data': deepcopy(self.raw.get('data', [])),
            'instruction': 'Preserve the original records. Generate required SEED INSERTs; future CREATED/DERIVED rows are not startup data.'}

    def check_database(self):
        if not self.root_read:
            raise ValueError('Read and implement root data before completion')
        self.design.ensure_complete()
        data = self.raw.get('data', [])
        seeds = [row for row in data if isinstance(row, dict) and row.get('lifecycle', 'SEED') == 'SEED'] if isinstance(data, list) else []
        if seeds and not any(re.search(r'\bINSERT\b', path.read_text(encoding='utf-8-sig'), re.I)
                for path in (self.arc_dir.parent / 'backend/src/db/seeds').glob('*.sql')):
            raise ValueError('Root data declares startup rows; implement their INSERT SQL before finishing')
        synchronize_loaders(self.arc_dir, self.schema)
        result = DatabaseChecks(self.arc_dir.parent, self.schema).run()
        save_json(self.arc_dir / 'db_checks.json',
            {'status': 'GREEN' if result['returncode'] == 0 else 'FAILED', 'checks': result})
        if result['returncode']:
            raise CheckFailure('Database initialization failed; repair the responsible SQL or startup files', result)
        return {'status': 'GREEN', 'checks': result}


def implement_database(arc_dir, pause=False, max_turns=40):
    schema, raw = read_artifact(arc_dir, 'db_schema.json'), read_artifact(arc_dir, 'requirements.json')
    console = DemoConsole(pause)
    synchronize_loaders(arc_dir, schema)
    install_dependencies(arc_dir.parent)
    try:
        agent = DatabaseBuildAgent(arc_dir, schema, raw, model=TextModel(json_mode=False))
        result = agent.run({'task': 'Implement schema batches, then original root data.',
            'schema_inventory': {name: list(entity['fields']) for name, entity in schema['entities'].items()},
            'schema_batches': agent.batches}, max_turns=max_turns, console=console, label='Implement database')
        report = {'status': 'GREEN', 'entities': len(schema['entities']), 'turns': result['turns']}
    except Exception as error:
        report = {'status': 'FAILED', 'error': str(error)}
        save_json(arc_dir / 'db_implementations.json', report)
        raise
    save_json(arc_dir / 'db_implementations.json', report)
    return report


def requirement_text(node):
    description = node.get('description', '')
    if isinstance(description, dict):
        description = description.get('text', '')
    return '\n'.join((str(node.get('name', '')), str(description),
        json.dumps(node.get('scenarios', []), ensure_ascii=False)))


def correct_database(input_dir, arc_dir, pause=False, max_turns=20):
    # No normalization of scenarios, strict field extraction or obligation contract.
    raw, schema = read_artifact(arc_dir, 'requirements.json'), read_artifact(arc_dir, 'db_schema.json')
    nodes = []
    def visit(node):
        nodes.append(node)
        for child in node.get('children', []) or []:
            visit(child)
    visit(raw)
    console, model = DemoConsole(pause), TextModel(json_mode=False)
    failures = TaskFailures(arc_dir, 'correct_db', console)
    report = {'status': 'RUNNING', 'batches': []}
    path = arc_dir / 'db_corrections.json'
    for offset in range(0, len(nodes), 5):
        batch = nodes[offset:offset + 5]
        ids = [node.get('id', str(offset + index)) for index, node in enumerate(batch)]
        label = 'batch ' + str(offset // 5 + 1)
        with failures.task(label):
            agent = DatabaseBuildAgent(arc_dir, schema, raw, correction=True, model=model)
            agent.run({'task': 'Review these requirements; repair actual database code only where needed.',
                'requirements_text': '\n\n---\n\n'.join(requirement_text(node) for node in batch),
                'schema_inventory': {name: list(entity['fields']) for name, entity in schema['entities'].items()}},
                max_turns=max_turns, console=console, label='Correct database '+label)
            checkpoint(arc_dir.parent, stage='correct_db', task=label,
                action='Publish requirement-driven database code corrections', status='GREEN')
        report['batches'].append({'requirements': ids, **failures.report['tasks'][label]})
        save_json(path, report)
    report['status'] = 'COMPLETED_WITH_FAILURES' if any(
        item['status'] == 'FAILED' for item in report['batches']) else 'GREEN'
    save_json(path, report)
    failures.finish()
    return report
