"""Portable I/O and process regressions; run with unittest on Linux or Windows."""

import json
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path, PureWindowsPath
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.shared.agent.files import FileWorkspace
from infrastructure.shared.project.entrypoints import import_path
from infrastructure.shared.project.initialize import initialize_project
from infrastructure.utils.files import read_artifact, read_source, save_json, save_text
from infrastructure.utils.paths import relative_path
from infrastructure.utils import processes


class PortableFiles(unittest.TestCase):
    """Exercise real edits and rollback with Windows-created source and Unicode paths."""

    def setUp(self):
        """Create an output root whose name requires correct Unicode/space handling."""
        self.temporary = TemporaryDirectory(prefix="arc portable ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "Workspace \u793a\u4f8b"
        self.root.mkdir()

    def test_lf_publication_and_bom_input(self):
        """Prevent CRCRLF growth without collapsing intentional blank lines."""
        source = self.root / "sample.ts"
        save_text(source, "first\r\r\n\r\nsecond\r\n")
        self.assertEqual(source.read_bytes(), b"first\n\nsecond\n")
        source.write_bytes(b"\xef\xbb\xbfhello\r\n")
        self.assertEqual(read_source(source), "hello\n")
        artifact = self.root / "data.json"
        artifact.write_bytes(b"\xef\xbb\xbf" + '{"name":"\u793a\u4f8b"}'.encode())
        self.assertEqual(read_artifact(self.root, "data.json"), {"name": "\u793a\u4f8b"})
        save_json(artifact, {"name": "\u793a\u4f8b"})
        self.assertNotIn(b"\r", artifact.read_bytes())

    def test_edits_accept_crlf_and_do_not_multiply_newlines(self):
        """Apply repeated model edits against normalized current contents."""
        relative = "backend/src/source.ts"
        target = self.root / relative
        target.parent.mkdir(parents=True)
        target.write_bytes(b"export const a = 1;\r\n\r\nexport const b = 2;\r\n")
        workspace = FileWorkspace(self.root, {relative})
        original = workspace.state()[relative]["content"]
        self.assertNotIn("\r", original)
        workspace.apply({"edits": [{"path": relative, "content": original.replace("a = 1", "a = 3")}]})
        workspace.state()
        workspace.apply({"edits": [{"path": relative, "content": read_source(target) + "export const c = 4;\r\n"}]})
        self.assertEqual(target.read_bytes(), b"export const a = 3;\n\nexport const b = 2;\nexport const c = 4;\n")

    def test_failed_batch_restores_exact_original_bytes(self):
        """A later write failure must restore prior writes with exact BOM/CRLF bytes."""
        relative = "backend/src/source.ts"
        target = self.root / relative
        target.parent.mkdir(parents=True)
        original = b"\xef\xbb\xbfexport const a = 1;\r\n"
        target.write_bytes(original)
        second = "backend/src/second.ts"
        workspace = FileWorkspace(self.root, {relative, second})
        workspace.state()
        def write(path, content):
            if path.name == "second.ts":
                raise OSError("Simulated write failure")
            save_text(path, content)
        with patch("infrastructure.shared.agent.files.save_text", side_effect=write):
            with self.assertRaisesRegex(OSError, "Simulated write"):
                workspace.apply({"edits": [{"path": relative, "content": "changed"}, {"path": second, "content": "new"}]})
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse((self.root / second).exists())

    def test_imports_use_posix_relative_paths_on_windows(self):
        """Simulate native Windows Path formatting while deriving module specifiers."""
        with patch("infrastructure.shared.project.entrypoints.Path", PureWindowsPath):
            self.assertEqual(import_path("backend/src/api/register.ts", "backend/src/handlers/login.ts"), "../handlers/login.js")
            self.assertEqual(import_path("frontend/src/App.tsx", "frontend/src/pages/home.tsx", extension=""), "./pages/home")

    def test_reserved_paths_and_case_collisions(self):
        """Reject paths that would escape, alias, or fail only after moving to Windows."""
        for name in ("C:/app.ts", "C:app.ts", "../app.ts", "backend\\src\\app.ts", "backend/CON.ts", "backend/file.", "backend/a:b.ts"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                relative_path(name)
        relative_path("backend/src/My Source \u793a\u4f8b.ts")
        save_text(self.root / "backend/src/Auth.ts", "// canonical\n")
        tools = FileWorkspace(self.root, set())
        with self.assertRaisesRegex(ValueError, "case"):
            tools.path("backend/src/auth.ts")

    def test_initialization_preserves_existing_sources(self):
        """Use portable LF templates under a path containing spaces and Unicode."""
        created = initialize_project(self.root)
        self.assertTrue(created)
        target = self.root / "frontend/src/App.tsx"
        self.assertNotIn(b"\r", target.read_bytes())
        target.write_bytes(b"// user code\r\n")
        self.assertEqual(initialize_project(self.root), [])
        self.assertEqual(target.read_bytes(), b"// user code\r\n")

    def test_model_file_interface_hides_native_paths(self):
        """Expose normalized relative files and actionable path errors without the host root."""
        relative = "backend/src/Auth.ts"
        target = self.root / relative
        target.parent.mkdir(parents=True)
        target.write_bytes(b"\xef\xbb\xbfexport const ready = true;\r\n")
        tools = FileWorkspace(self.root, set(), references=[relative])
        state = tools.state()
        self.assertEqual(state, {relative: {"content": "export const ready = true;\n", "writable": False}})
        self.assertNotIn(str(self.root), json.dumps(state))
        for invalid in ("backend/src/auth.ts", "backend/src/CON.ts"):
            with self.subTest(path=invalid), self.assertRaises(ValueError) as rejected:
                tools.path(invalid)
            message = str(rejected.exception)
            self.assertNotIn(str(self.root), message)
            self.assertNotIn("Windows", message)
            self.assertNotIn("Linux", message)


class PortableProcesses(unittest.TestCase):
    """Test actual command arguments and mocked Windows process control without a shell."""

    def test_npm_cmd_resolves_to_node_cli(self):
        """Spaces in npm's Windows installation directory must not become shell syntax."""
        with TemporaryDirectory(prefix="Program Files ") as temporary:
            directory = Path(temporary)
            node = directory / "node.exe"
            launcher = directory / "npm.cmd"
            cli = directory / "node_modules/npm/bin/npm-cli.js"
            node.touch(); launcher.touch(); cli.parent.mkdir(parents=True); cli.touch()
            with patch.object(processes.shutil, "which", side_effect=lambda name: str(node if name == "node" else launcher)):
                self.assertEqual(processes.npm_command(), [str(node), str(cli)])

    def test_windows_group_and_owned_tree_cleanup(self):
        """Windows uses CREATE_NEW_PROCESS_GROUP/taskkill rather than POSIX signals."""
        self.assertEqual(processes.child_environment({"PYTHONUTF8": "0"})["PYTHONUTF8"], "1")
        process = Mock(pid=321)
        process.poll.return_value = 0
        with patch.object(processes, "WINDOWS", True), patch.object(processes.subprocess, "run") as run, patch.object(processes.shutil, "which", return_value="taskkill.exe"):
            self.assertIn("creationflags", processes.process_options())
            self.assertNotIn("start_new_session", processes.process_options())
            processes.stop_process(process)
            self.assertEqual(run.call_args.args[0], ["taskkill.exe", "/PID", "321", "/T", "/F"])

    def test_utf8_arguments_environment_and_cwd(self):
        """Capture real Unicode child output and arguments with shell metacharacters intact."""
        with TemporaryDirectory(prefix="arc cwd ") as temporary:
            directory = Path(temporary) / "\u793a\u4f8b & space"
            directory.mkdir()
            value = "space & percent% \u793a\u4f8b"
            result = processes.capture_process([sys.executable, "-c",
                "import json,os,sys;print(json.dumps([sys.argv[1],os.getcwd(),os.environ['PYTHONIOENCODING']],ensure_ascii=False))", value], cwd=directory, timeout=10)
            self.assertEqual(result["returncode"], 0)
            self.assertEqual(json.loads(result["stdout"]), [value, str(directory), "utf-8"])

    def test_timeout_stops_descendants(self):
        """A timed-out parent must not leave a heartbeat-writing child alive."""
        with TemporaryDirectory(prefix="arc process ") as temporary:
            directory = Path(temporary)
            marker = directory / "heartbeat"
            child = "import time,pathlib; p=pathlib.Path('heartbeat');\nwhile True:\n p.open('a').write('x'); time.sleep(.03)"
            parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); time.sleep(60)"
            with self.assertRaises(subprocess.TimeoutExpired):
                processes.capture_process([sys.executable, "-c", parent, child], cwd=directory, timeout=2)
            self.assertTrue(marker.is_file())
            before = marker.read_bytes()
            time.sleep(.2)
            self.assertEqual(marker.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
