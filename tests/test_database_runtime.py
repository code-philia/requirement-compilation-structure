"""Real SQLite/startup failures must be repaired by the database-owning task."""
from tool_fixtures import propose_files

from contextlib import redirect_stdout
from importlib import import_module
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.agent.tasks import StageIncomplete
from infrastructure.shared.project.initialize import initialize_project
from infrastructure.shared.agent.tools import FileTools
from infrastructure.stages.database.implementation import verify_database_runtime
from infrastructure.stages.database.runtime import initializer_source
from infrastructure.stages.database.testing import DatabaseChecks
from infrastructure.utils.files import save_json, save_text


SQL = 'CREATE TABLE IF NOT EXISTS "Note" ("id" INTEGER PRIMARY KEY, "tags" TEXT NOT NULL CHECK(json_valid("tags") AND json_type("tags") = \'array\'));'
BAD_SQL = 'CREATE TABLE IF NOT EXISTS "Note" ("id" INTEGER PRIMARY KEY, "tags" TEXT CHECK(NOT EXISTS (SELECT 1 FROM json_each("tags"))));'


def schema():
    def field(kind, primary=False):
        return {'description': 'Persistent value', 'type': kind, 'nullable': False,
            'primary_key': primary, 'unique': False, 'references': None, 'constraints': []}
    return {'entities': {'Note': {'description': 'Saved notes', 'fields': {
        'id': field('integer', True), 'tags': field('json')}}}, 'requirements': {}}


def prepare(output, sql=SQL):
    initialize_project(output)
    arc = output / '.arc'
    save_json(arc / 'requirements.json', {'id': 'ROOT'})
    save_json(arc / 'db_schema.json', schema())
    save_text(output / 'backend/src/db/tables/Note.sql', sql)
    save_text(output / 'backend/src/db/initialize.ts', initializer_source({'Note': {'path': 'Note.sql'}}))
    return arc


class DatabaseRepairProtocol(unittest.TestCase):
    def test_file_discovery_can_expand_database_edit_permissions(self):
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            output = Path(temporary)
            arc = prepare(output)
            data = schema()
            data['entities']['Audit'] = data['entities']['Note']
            save_json(arc / 'db_schema.json', data)
            other = 'backend/src/db/tables/Audit.sql'
            save_text(output / other, SQL.replace('Note', 'Audit'))
            calls = []
            def generate(instructions, payload):
                calls.append(payload)
                if len(calls) == 1:
                    self.assertNotIn(other, payload['files'])
                    self.assertIn('Note', payload['task']['entities'])
                    self.assertIn('backend/src/db/tables/Note.sql', payload['files'])
                    return {'tool_calls': [{'tool': 'read_file', 'arguments': {'path': other}}]}
                self.assertNotIn(other, payload['files'])
                self.assertTrue(payload['context_result']['tool_results'][0]['result']['writable'])
                return propose_files(output, [{'path': other, 'content': SQL.replace('Note', 'Audit')}])
            checks = Mock()
            checks.run.side_effect = [{'returncode': 1, 'error': 'Missing table: Note\n at initialize'},
                {'returncode': 0, 'status': 'GREEN'}]
            with patch('infrastructure.stages.database.implementation.DatabaseChecks', return_value=checks), \
                    patch('infrastructure.stages.database.implementation.install_dependencies'):
                result = verify_database_runtime(arc, data, Mock(generate_json=generate), Mock(), max_turns=1)
            self.assertEqual(result['status'], 'GREEN')
            self.assertEqual(len(calls), 2)

    def test_queried_sql_is_editable_only_for_the_database_owner(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            path = 'backend/src/db/tables/Note.sql'
            save_text(output / path, BAD_SQL)
            workspace = FileTools(output, allow_write=lambda candidate: candidate == path)
            workspace.files.add(path)
            self.assertTrue(workspace.state()[path]['writable'])
            workspace.execute(propose_files(output, [{'path': path, 'content': SQL}])["tool_calls"])
            from infrastructure.shared.agent.context import SourceFiles
            ordinary = SourceFiles(output, root='backend/src', tests_root='backend/tests').workspace(references=[path])
            self.assertFalse(ordinary.state()[path]['writable'])

    def test_missing_sql_can_be_created_after_real_failure_and_marked_recovered(self):
        stage = import_module('05_implement_db')
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            output = Path(temporary)
            arc = prepare(output)
            (output / 'backend/src/db/tables/Note.sql').unlink()
            def verify(arc_dir, db_schema, model, console, max_turns):
                save_text(output / 'backend/src/db/tables/Note.sql', SQL)
                return {'status': 'GREEN'}
            with patch.object(stage, 'TextModel', return_value=Mock(generate_json=Mock(return_value={}))), \
                    patch.object(stage, 'verify_database_runtime', side_effect=verify):
                result = stage.implement_db(arc, max_attempts=1)
            self.assertEqual(result['Note']['content'].strip(), SQL)
            report = json.loads((arc / 'stage_tasks/05_implement_db.json').read_text())
            self.assertEqual(report['status'], 'GREEN')
            self.assertEqual(report['tasks']['Note']['recovered_by'], 'database runtime repair')


class RealDatabaseRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        modules = Path(os.environ.get('ARC_DB_TEST_NODE_MODULES', 'node_modules')).resolve()
        if not all((modules / name).exists() for name in ('better-sqlite3', 'tsx', 'typescript', 'express')):
            raise unittest.SkipTest('Set ARC_DB_TEST_NODE_MODULES to installed generated-app dependencies')
        cls.modules = modules

    def workspace(self, directory, sql=SQL):
        output = Path(directory)
        arc = prepare(output, sql)
        (output / 'node_modules').symlink_to(self.modules, target_is_directory=True)
        return output, arc

    def test_real_initialization_repeat_missing_table_and_compiled_server_restart(self):
        with TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            output, arc = self.workspace(directory)
            # Existing application data must survive the successful output initialization.
            first = DatabaseChecks(output, schema()).run()
            self.assertEqual(first['returncode'], 0, first)
            self.assertEqual(first['completed'], ['fresh initialization', 'repeated initialization',
                'missing-table recovery', 'compiled initialization', 'fresh server startup',
                'server restart', 'output database initialization'])
            self.assertTrue((output / 'backend/data/app.db').is_file())
            script = "const D=require('better-sqlite3');const d=new D('backend/data/app.db');d.prepare('INSERT INTO Note(id,tags) VALUES(1,?)').run('[\"saved\"]');d.close();"
            from infrastructure.utils.processes import capture_process
            seeded = capture_process(['node', '-e', script], cwd=output, timeout=30)
            self.assertEqual(seeded['returncode'], 0, seeded)
            result = DatabaseChecks(output, schema()).run()
            self.assertEqual(result['returncode'], 0, result)
            observed = capture_process(['node', '-e', "const D=require('better-sqlite3');const d=new D('backend/data/app.db');console.log(d.prepare('SELECT tags FROM Note WHERE id=1').get().tags);d.close();"], cwd=output, timeout=30)
            self.assertEqual(observed['stdout'].strip(), '["saved"]')

    def test_invalid_sql_gets_concrete_file_feedback_and_real_edit_repair(self):
        with TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            output, arc = self.workspace(directory, BAD_SQL)
            requests = []
            def repair(instructions, payload):
                requests.append(payload)
                self.assertIn('Note.sql', json.dumps(payload['feedback']))
                if len(requests) == 1:
                    self.assertIn('subqueries prohibited', json.dumps(payload['feedback']))
                else:
                    self.assertIn('already exists', json.dumps(payload['feedback']))
                    self.assertIn('repeated initialization', json.dumps(payload['feedback']))
                self.assertTrue(payload['files']['backend/src/db/tables/Note.sql']['writable'])
                self.assertTrue(payload['files']['backend/src/db/initialize.ts']['writable'])
                return propose_files(output, [{'path': 'backend/src/db/tables/Note.sql',
                        'content': SQL.replace('IF NOT EXISTS ', '') if len(requests) == 1 else SQL}], diagnosis={'cause': 'implementation', 'reason': 'SQLite rejects subqueries in Note CHECK'})
            report = verify_database_runtime(arc, schema(), Mock(generate_json=repair), Mock(), max_turns=2)
            self.assertEqual(report['status'], 'GREEN')
            self.assertEqual(report['repair_turns'], 2)
            self.assertEqual(len(requests), 2)
            self.assertTrue((output / 'backend/data/app.db').is_file())

    def test_initializer_wiring_is_editable_and_not_overwritten_after_repair(self):
        with TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            output, arc = self.workspace(directory)
            path = 'backend/src/db/initialize.ts'
            save_text(output / path, (output / path).read_text().replace('[\n  "Note.sql"\n]', '[]'))
            self.assertIn('= [];', (output / path).read_text())
            def repair(instructions, payload):
                self.assertIn('Missing table: Note', json.dumps(payload['feedback']))
                return propose_files(output, [{'path': path, 'content': initializer_source({'Note': {'path': 'Note.sql'}})}])
            report = verify_database_runtime(arc, schema(), Mock(generate_json=repair), Mock(), max_turns=1)
            self.assertEqual(report['status'], 'GREEN')
            self.assertIn('Note.sql', (output / path).read_text())

    def test_server_without_initialization_is_rejected_and_repaired(self):
        with TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            output, arc = self.workspace(directory)
            path = 'backend/src/server.ts'
            source = (output / path).read_text()
            save_text(output / path, source.replace('initializeDatabase(connection);', ''))
            def repair(instructions, payload):
                self.assertIn('fresh server startup', json.dumps(payload['feedback']))
                self.assertTrue(payload['files'][path]['writable'])
                return propose_files(output, [{'path': path, 'content': source}])
            report = verify_database_runtime(arc, schema(), Mock(generate_json=repair), Mock(), max_turns=1)
            self.assertEqual(report['status'], 'GREEN')

    def test_stage_fails_honestly_after_repair_exhaustion(self):
        stage = import_module('05_implement_db')
        with TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            output, arc = self.workspace(directory)
            def response(instructions, payload):
                return propose_files(output, [{'path': payload['task']['output_path'], 'content': BAD_SQL}]) if 'entity_name' in payload['task'] else propose_files(output, [])
            with patch.object(stage, 'TextModel', return_value=Mock(generate_json=response)):
                with self.assertRaises(StageIncomplete):
                    stage.implement_db(arc, max_attempts=1, max_turns=1)
            report = json.loads((arc / 'db_checks.json').read_text())
            self.assertEqual(report['status'], 'FAILED')
            tasks = json.loads((arc / 'stage_tasks/05_implement_db.json').read_text())
            self.assertEqual(tasks['tasks']['database runtime']['status'], 'FAILED')
            self.assertFalse((output / 'backend/data/app.db').exists())

    def test_runtime_repair_recovers_a_failed_generation_and_its_missing_wiring(self):
        stage = import_module('05_implement_db')
        with TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            output, arc = self.workspace(directory)
            path = 'backend/src/db/tables/Note.sql'
            (output / path).unlink()
            def response(instructions, payload):
                if 'entity_name' in payload['task']:
                    return {}
                self.assertIn('Note', payload['task']['entities'])
                self.assertIsNone(payload['files'][path]['content'])
                return propose_files(output, [{'path': path, 'content': SQL},
                    {'path': 'backend/src/db/initialize.ts',
                        'content': initializer_source({'Note': {'path': 'Note.sql'}})}])
            with patch.object(stage, 'TextModel', return_value=Mock(generate_json=response)):
                result = stage.implement_db(arc, max_attempts=1, max_turns=1)
            self.assertEqual(result['Note']['content'].strip(), SQL)
            report = json.loads((arc / 'stage_tasks/05_implement_db.json').read_text())
            self.assertEqual(report['status'], 'GREEN')
            self.assertEqual(report['tasks']['Note']['recovered_by'], 'database runtime repair')
