"""Real Git history preserves accepted work, rejected edits, and honest final reports."""
from tool_fixtures import propose_files

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from infrastructure.compiler import Compiler
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.recovery import implementation_task
from infrastructure.shared.agent.tasks import StageIncomplete, TaskFailures
from infrastructure.shared.project.git import GitError, GitRepository, checkpoint, initialize_repository
from infrastructure.utils.files import save_json, save_text


class GitCheckpoints(unittest.TestCase):
    def test_nested_output_has_its_own_main_and_excludes_runtime_data(self):
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            parent = GitRepository(temporary).initialize()
            output = Path(temporary) / 'application 中文 with spaces'
            repository = initialize_repository(output)
            self.assertIsNotNone(repository)
            self.assertEqual(repository.run('branch', '--show-current').stdout.strip(), 'main')
            self.assertEqual(Path(repository.run('rev-parse', '--show-toplevel').stdout.strip()), output)
            for path in ('backend/src/api/example.ts', '.arc/db_schema.json', '.env.example',
                         'node_modules/example.js', 'backend/dist/server.js', 'backend/data/app.db',
                         'frontend/test-results/trace.zip', '.arc/model_logs/request.model.input',
                         '.env', '.env.local', 'compiler.log', 'model_calls.jsonl'):
                save_text(output / path, 'example')
            checkpoint(output, stage='02', task='REQ-1', action='Publish schema', details={'entities': ['Note']})
            tracked = set(repository.run('ls-files').stdout.splitlines())
            self.assertEqual(tracked, {'.gitignore', '.arc/db_schema.json', '.env.example', 'backend/src/api/example.ts'})
            self.assertTrue(parent.run('rev-parse', '--verify', 'HEAD', check=False).returncode)
            message = repository.run('log', '-1', '--format=%B').stdout
            self.assertIn('Task: REQ-1', message)
            self.assertIn('Changed files:', message)
            self.assertIn('Note', message)
            self.assertEqual(repository.status(), '')

    def test_existing_branch_is_renamed_without_losing_history(self):
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            repository = initialize_repository(temporary)
            original = repository.run('rev-parse', 'HEAD').stdout.strip()
            repository.run('branch', '-m', 'old-branch')
            initialize_repository(temporary)
            self.assertEqual(repository.run('branch', '--show-current').stdout.strip(), 'main')
            self.assertEqual(repository.run('rev-parse', 'HEAD').stdout.strip(), original)
            checkpoint(temporary, stage='04', task='validation', action='Check field symbols')
            self.assertEqual(repository.run('rev-list', '--count', 'HEAD').stdout.strip(), '2')
            self.assertIn('No tracked file changes', repository.run('log', '-1', '--format=%B').stdout)

    def test_missing_identity_uses_command_local_defaults(self):
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            root = Path(temporary)
            with patch.dict('os.environ', {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': str(root / 'absent-config'),
                    'GIT_AUTHOR_NAME': '', 'GIT_AUTHOR_EMAIL': '', 'GIT_COMMITTER_NAME': '', 'GIT_COMMITTER_EMAIL': ''}):
                # Empty identity variables override even -c settings, so remove them for this clean environment.
                import os
                for key in ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL'):
                    os.environ.pop(key, None)
                repository = initialize_repository(root / 'application')
                self.assertIsNotNone(repository)
                self.assertEqual(repository.run('log', '-1', '--format=%an <%ae>').stdout.strip(),
                    'Requirement Compiler <compiler@localhost>')
                self.assertTrue(repository.run('config', '--local', '--get', 'user.email', check=False).returncode)
                self.assertFalse((root / 'absent-config').exists())

    def test_task_failure_and_later_success_are_separate_snapshots(self):
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            root = Path(temporary)
            repository = initialize_repository(root)
            tasks = TaskFailures(root / '.arc', '02_build_db_schema', Mock())
            with tasks.task('BAD'):
                raise ValueError('Invalid schema proposal')
            with tasks.task('GOOD'):
                save_json(root / '.arc/db_schema.json', {'entities': {'Note': {}}})
            with self.assertRaises(StageIncomplete):
                tasks.finish()
            history = repository.log()
            self.assertIn('BAD: Publish design task result (FAILED)', history)
            self.assertIn('GOOD: Publish design task result (GREEN)', history)
            report = json.loads(repository.run('show', 'HEAD:.arc/stage_tasks/02_build_db_schema.json').stdout)
            self.assertEqual(report['status'], 'COMPLETED_WITH_FAILURES')
            self.assertEqual(report['tasks']['GOOD']['status'], 'GREEN')

    def test_rejected_edit_is_preserved_in_history_before_baseline_restoration(self):
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            root = Path(temporary)
            repository = initialize_repository(root)
            path = 'backend/src/api/note.ts'
            save_text(root / path, 'accepted baseline')
            checkpoint(root, stage='08', task='baseline', action='Save accepted source')
            entry = {'status': 'IMPLEMENTING'}
            model = Mock(generate_json=Mock(return_value=propose_files(root, [{'path': path, 'content': 'rejected implementation'}], diagnosis={'cause': 'implementation', 'reason': 'Missing result'})))
            with implementation_task(root, entry, Mock(), '08 / API-NOTE'):
                run_file_agent(model, '', {}, FileTools(root, [path]),
                    Mock(side_effect=ValueError('Business result is wrong')), 1, Mock(), 'API-NOTE')
            self.assertEqual(entry['status'], 'FAILED')
            self.assertEqual((root / path).read_text(), 'accepted baseline')
            self.assertEqual(repository.run('show', f'HEAD~2:{path}').stdout, 'rejected implementation')
            self.assertEqual(repository.run('show', f'HEAD:{path}').stdout, 'accepted baseline')
            self.assertIn('Archive failed attempt', repository.log())
            archive = entry['archive'] + '/failure.json'
            self.assertEqual(json.loads(repository.run('show', 'HEAD:' + archive).stdout)['status'], 'FAILED')
            self.assertEqual(repository.status(), '')

    def test_pipeline_commits_each_pass_and_final_partial_report(self):
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            from test_compiler import PASSES
            root = Path(temporary)
            compiler = Compiler(root / 'input', root / 'output')
            def load(module):
                name = next(function for stage, function in PASSES if stage == module)
                def execute(*args, **kwargs):
                    if module.startswith('03'):
                        raise ValueError('Missing obligation')
                    return {'status': 'GREEN'}
                return SimpleNamespace(**{name: execute})
            with patch('infrastructure.compiler.import_module', side_effect=load):
                compiler.compile()
            repository = GitRepository(compiler.output_dir)
            history = repository.log(100)
            for module, _ in PASSES:
                self.assertIn(f'[{module}] stage report: Publish pass result', history)
            report = json.loads(repository.run('show', 'HEAD:.arc/compilation.json').stdout)
            self.assertEqual(report['status'], 'COMPLETED_WITH_FAILURES')
            self.assertEqual(report['stages']['03_infer_db_obligations']['status'], 'FAILED')
            self.assertIn('Publish final compilation report (COMPLETED_WITH_FAILURES)', history)
            self.assertEqual(repository.status(), '')

    def test_git_errors_do_not_replace_model_or_acceptance_results(self):
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()) as console:
            with patch('infrastructure.shared.project.git.subprocess.run', side_effect=FileNotFoundError('git unavailable')):
                self.assertIsNone(initialize_repository(temporary))
            self.assertIn('[GIT WARNING]', console.getvalue())
            repository = initialize_repository(temporary)
            with patch.object(GitRepository, 'commit', side_effect=GitError('Commit unavailable')):
                self.assertIsNone(checkpoint(temporary, task='check', action='Record result'))
                root = Path(temporary)
                path = 'backend/src/accepted.ts'
                save_text(root / path, 'before')
                model = Mock(generate_json=Mock(return_value=propose_files(root, [{'path': path, 'content': 'after'}])))
                accepted = run_file_agent(model, '', {}, FileTools(root, [path]),
                    Mock(return_value={'returncode': 0}), 1, Mock(), 'implementation')
                self.assertEqual(accepted['checks']['returncode'], 0)
                self.assertEqual((root / path).read_text(), 'after')
            self.assertEqual(repository.run('branch', '--show-current').stdout.strip(), 'main')

    def test_detached_head_does_not_receive_compiler_commits(self):
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            repository = initialize_repository(temporary)
            original = repository.run('rev-parse', 'HEAD').stdout.strip()
            repository.run('checkout', '--detach', 'HEAD')
            self.assertIsNone(initialize_repository(temporary))
            self.assertIsNone(checkpoint(temporary, task='check', action='Record result'))
            self.assertEqual(repository.run('rev-parse', 'HEAD').stdout.strip(), original)

    def test_output_commands_ignore_parent_git_environment(self):
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            parent = GitRepository(Path(temporary) / 'parent').initialize()
            output = Path(temporary) / 'output'
            with patch.dict('os.environ', {'GIT_DIR': str(parent.directory / '.git'), 'GIT_WORK_TREE': str(parent.directory)}):
                repository = initialize_repository(output)
                self.assertIsNotNone(repository)
                self.assertEqual(Path(repository.run('rev-parse', '--show-toplevel').stdout.strip()), output)


if __name__ == '__main__':
    unittest.main()
