"""Verify the direct stage pipeline, portable CLI paths and template port injection."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import compiler as pipeline_module
import main as entrypoint
from infrastructure.shared.project.initialize import STACKS, DEFAULT_STACK, initialize_project
from infrastructure.stages.requirements.exploration import explore_requirement
from infrastructure.utils.presentation.logging import session_info


BEHAVIORS = (
    "project_initialization", "explore_requirement", "build_db_schema", "infer_db_obligations",
    "check_db_obligations", "implement_db", "decompose_backend_apis", "infer_api_contracts",
    "implement_backend_tdd", "design_frontend_ui", "implement_frontend_ui",
    "design_ui_interactions", "implement_frontend_interactions",
)


class CompilerPipeline(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.input_dir = self.root / "source with spaces"
        self.input_dir.mkdir()
        self.source = self.input_dir / "custom-document.yml"
        self.source.write_text("id: ROOT\nname: Demo\nchildren: []\n", encoding="utf-8")
        self.output = self.root / "output with spaces"

    def test_cli_arguments_and_both_long_output_spellings(self):
        for flag in ("-o", "--output-dir", "--ouput-dir"):
            with self.subTest(flag=flag), patch.object(entrypoint, "Compiler") as cls:
                entrypoint.main([str(self.source), flag, str(self.output), "--port", "4321"])
                cls.assert_called_once_with(self.source, self.output, 4321)
                cls.return_value.compile.assert_called_once_with()
        args = entrypoint.build_parser().parse_args([str(self.source), "-o", str(self.output)])
        self.assertEqual(args.port, 3000)

    def test_all_stages_run_in_order_with_one_workspace_and_stage_log_context(self):
        instance = pipeline_module.Compiler(self.source, self.output, 4321)
        calls = []

        def behavior(name):
            def execute(*args, **kwargs):
                calls.append((name, args, kwargs, session_info()["stage"]))
            return execute

        with ExitStack() as stack, redirect_stdout(StringIO()):
            for name in BEHAVIORS:
                stack.enter_context(patch.object(pipeline_module, name, side_effect=behavior(name)))
            self.assertEqual(instance.compile(), self.output)
        self.assertEqual([call[0] for call in calls], list(BEHAVIORS))
        self.assertEqual(instance.completed_stages, [f"{i:02d}" for i in range(13)])
        self.assertEqual(calls[0][1:], ((self.output,), {"port": 4321}, "Stage 00 | Initialize project"))
        self.assertEqual(calls[1][1], (self.input_dir, self.output / ".arc"))
        self.assertEqual(calls[1][2], {"requirement_path": self.source})
        for index, call in enumerate(calls):
            self.assertIn(f"Stage {index:02d}", call[3])
        self.assertIsNone(session_info())

    def test_failure_stops_before_later_stages(self):
        instance = pipeline_module.Compiler(self.source, self.output)
        with ExitStack() as stack, redirect_stdout(StringIO()):
            mocks = {name: stack.enter_context(patch.object(pipeline_module, name)) for name in BEHAVIORS}
            mocks["build_db_schema"].side_effect = RuntimeError("Schema synthesis failed")
            with self.assertRaisesRegex(RuntimeError, "Schema synthesis failed"):
                instance.compile()
        self.assertEqual(instance.completed_stages, ["00", "01"])
        self.assertIn("Stage 02", instance.current_stage)
        mocks["infer_db_obligations"].assert_not_called()
        mocks["implement_frontend_interactions"].assert_not_called()

    def test_invalid_inputs_fail_before_initialization(self):
        for port in (0, 65536, -1, True, "3000"):
            with self.subTest(port=port), self.assertRaisesRegex(ValueError, "Port"):
                pipeline_module.Compiler(self.source, self.output, port)
        with self.assertRaisesRegex(ValueError, "does not exist"):
            pipeline_module.Compiler(self.input_dir / "absent.yaml", self.output)
        with self.assertRaisesRegex(ValueError, "inside the input"):
            pipeline_module.Compiler(self.source, self.input_dir / "output")
        self.assertFalse(self.output.exists())

    def test_template_port_is_workspace_local_and_preserves_existing_sources(self):
        template = STACKS[DEFAULT_STACK]["templates"] / "backend/src/server.ts"
        original = template.read_bytes()
        initialize_project(self.output, port=4321)
        server = self.output / "backend/src/server.ts"
        self.assertIn('process.env.PORT ?? "4321"', server.read_text())
        self.assertEqual(template.read_bytes(), original)
        server.write_text("// Existing application source\n", encoding="utf-8")
        self.assertEqual(initialize_project(self.output, port=5432), [])
        self.assertEqual(server.read_text(), "// Existing application source\n")

    def test_custom_requirement_filename_and_source_relative_images(self):
        image = self.input_dir / "reference/page.png"
        image.parent.mkdir()
        image.write_bytes(b"test image handled by the fake vision model")
        self.source.write_text("id: ROOT\nname: Demo\ndescription:\n  image:\n    - reference: reference/page.png\n", encoding="utf-8")
        model = Mock()
        model.analyze.return_value = {"layout": "one page", "elements": [], "style": "plain"}
        with patch("infrastructure.stages.requirements.exploration.VisualModel", return_value=model), redirect_stdout(StringIO()):
            explore_requirement(self.input_dir, self.output / ".arc", requirement_path=self.source)
        model.analyze.assert_called_once_with(image)
        result = json.loads((self.output / ".arc/requirements.json").read_text())
        self.assertEqual(result["id"], "ROOT")

    def test_main_pipeline_survives_removal_of_all_numbered_scripts(self):
        isolated = self.root / "distributed compiler"
        isolated.mkdir()
        original = Path(pipeline_module.__file__).parent
        for name in ("main.py", "compiler.py"):
            shutil.copy2(original / name, isolated / name)
        shutil.copytree(original / "infrastructure", isolated / "infrastructure",
                        ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
        probe = """
from contextlib import ExitStack
from unittest.mock import patch
from pathlib import Path
import compiler
names = %r
instance = compiler.Compiler(Path(%r), Path(%r), 4321)
with ExitStack() as stack:
    for name in names:
        stack.enter_context(patch.object(compiler, name))
    instance.compile()
assert instance.completed_stages == [f'{i:02d}' for i in range(13)]
""" % (BEHAVIORS, str(self.source), str(self.output))
        result = subprocess.run([sys.executable, "-c", probe], cwd=isolated, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        help_result = subprocess.run([sys.executable, "main.py", "--help"], cwd=isolated, capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--port", help_result.stdout)

    def test_cli_reports_failure_without_claiming_completion(self):
        with patch.object(entrypoint, "Compiler") as cls, redirect_stderr(StringIO()) as errors:
            cls.return_value.current_stage = "Stage 08 | Backend TDD"
            cls.return_value.compile.side_effect = RuntimeError("Frozen tests are still red")
            with self.assertRaises(SystemExit) as raised:
                entrypoint.main([str(self.source), "-o", str(self.output)])
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("Stage 08", errors.getvalue())
        self.assertIn("Frozen tests are still red", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
