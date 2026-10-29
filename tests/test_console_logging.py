"""Exercise bounded console output and complete I/O at the real SDK boundary."""

from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI

from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole, preview, show_panel, display_width
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.presentation.model_io import _http_request, _http_response, invoke


class ConsoleLogging(unittest.TestCase):
    """Run SDK serialization and retry handling without remote model requests."""

    def model(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler),
            event_hooks={"request": [_http_request], "response": [_http_response]})
        self.addCleanup(client.close)
        model = TextModel.__new__(TextModel)
        model.client = OpenAI(api_key="test-secret", base_url="https://model.test/v1", http_client=client, max_retries=1)
        self.addCleanup(model.client.close)
        model.name = "test-model"
        model.max_output_tokens = 1024
        model._token_parameter = "max_completion_tokens"
        return model

    def response(self, content, finish="stop"):
        return {"id": "chat-test", "object": "chat.completion", "created": 0, "model": "test-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}

    def test_console_is_bounded_but_panels_and_model_io_are_complete(self):
        source = "export const answer = 42;\n" * 1000 + "END-OF-SOURCE"
        raw_content = json.dumps({"edits": [{"path": "frontend/src/page.tsx", "content": source}]})
        model = self.model(lambda request: httpx.Response(200, json=self.response(raw_content)))
        terminal = StringIO()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("sys.argv", ["10_implement_ui.py"]), redirect_stdout(terminal), redirect_stderr(terminal), console_log(root):
                DemoConsole().show("PAGE-home | Input context", "INPUT-DETAIL\n" * 1000 + "END-OF-PANEL")
                result = model.generate_json("Implement UI.", {"files": {"page.tsx": {"content": source, "writable": True}}})
            records = [json.loads(line) for line in (root / "model_calls.jsonl").read_text().splitlines()]
            compiler_log = (root / "compiler.log").read_text()
        self.assertEqual(result["edits"][0]["content"], source)
        self.assertNotIn("END-OF-PANEL", terminal.getvalue())
        self.assertNotIn("END-OF-SOURCE", terminal.getvalue())
        self.assertIn("END-OF-PANEL", compiler_log)
        self.assertIn("Stage 10", terminal.getvalue())
        self.assertIn("[WAITING]", terminal.getvalue())
        self.assertIn("frontend/src/page.tsx", terminal.getvalue())
        self.assertIn("export const answer = 42", terminal.getvalue())
        self.assertIn("truncated", terminal.getvalue())
        self.assertEqual([item["event"] for item in records], ["request", "http_request", "http_response", "response"])
        wire_request = json.loads(records[1]["body"])
        self.assertEqual(wire_request, records[0]["arguments"])
        self.assertTrue(wire_request["messages"][0]["content"].endswith("Return exactly one JSON object without Markdown."))
        self.assertEqual(json.loads(records[2]["body"])["choices"][0]["message"]["content"], raw_content)
        self.assertEqual(records[3]["response"]["choices"][0]["message"]["content"], raw_content)
        self.assertEqual(len({record["call_id"] for record in records}), 1)
        self.assertNotIn("test-secret", json.dumps(records))

    def test_http_retry_and_parameter_fallback_record_actual_attempts(self):
        attempts = []
        def handler(request):
            body = json.loads(request.content)
            attempts.append(body)
            if len(attempts) == 1:
                return httpx.Response(500, headers={"retry-after-ms": "1"}, json={"error": {"message": "Temporary failure"}})
            if "max_completion_tokens" in body:
                return httpx.Response(400, json={"error": {"message": "Unsupported parameter max_completion_tokens"}})
            return httpx.Response(200, json=self.response('{"ok":true}'))
        model = self.model(handler)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with redirect_stdout(StringIO()), console_log(root):
                self.assertEqual(model.generate_json("Generate.", {}), {"ok": True})
            records = [json.loads(line) for line in (root / "model_calls.jsonl").read_text().splitlines()]
        requests = [json.loads(record["body"]) for record in records if record["event"] == "http_request"]
        self.assertEqual(requests, attempts)
        self.assertEqual(len(requests), 3)
        self.assertIn("max_completion_tokens", requests[0])
        self.assertIn("max_tokens", requests[2])
        self.assertEqual([record["status_code"] for record in records if record["event"] == "http_response"], [500, 400, 200])

    def test_invalid_and_truncated_content_is_logged_before_parsing(self):
        for content, finish in [("{broken-json", "stop"), ('{"partial":', "length")]:
            with self.subTest(finish=finish), TemporaryDirectory() as temporary:
                model = self.model(lambda request: httpx.Response(200, json=self.response(content, finish)))
                root = Path(temporary)
                with redirect_stdout(StringIO()), console_log(root), self.assertRaises(ValueError):
                    model.generate_json("Generate.", {})
                records = [json.loads(line) for line in (root / "model_calls.jsonl").read_text().splitlines()]
                self.assertEqual(records[-1]["response"]["choices"][0]["message"]["content"], content)

    def test_image_data_is_full_in_logs_and_absent_from_terminal(self):
        model = self.model(lambda request: httpx.Response(200, json=self.response('{"layout":"visible"}')))
        image_data = "data:image/png;base64," + "QUJD" * 2000
        arguments = {"model": model.name, "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Analyze visible evidence."},
            {"type": "image_url", "image_url": {"url": image_data, "detail": "high"}},
        ]}]}
        terminal = StringIO()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with redirect_stdout(terminal), console_log(root):
                invoke(model.client, arguments)
            records = [json.loads(line) for line in (root / "model_calls.jsonl").read_text().splitlines()]
        self.assertNotIn("QUJD", terminal.getvalue())
        self.assertEqual(json.loads(records[1]["body"]), arguments)

    def test_preview_limits_single_line_and_many_short_lines(self):
        self.assertLess(len(preview("x" * 1000000)), 6000)
        self.assertLess(len(preview("x\n" * 1000000)), 6000)
        self.assertEqual(preview("complete"), "complete")

    def test_panel_aligns_wide_text_and_long_titles_on_narrow_terminals(self):
        import os
        terminal = StringIO()
        with redirect_stdout(terminal), patch("shutil.get_terminal_size", return_value=os.terminal_size((45, 24))):
            show_panel("Stage 11 | REQ-REGISTER | Interaction design", "中文内容 and e\u0301\n" + "长" * 80)
        rows = [row for row in terminal.getvalue().splitlines() if row]
        self.assertTrue(rows[0].startswith("┌"))
        self.assertTrue(rows[-1].startswith("└"))
        self.assertEqual({display_width(row) for row in rows}, {45})
        self.assertIn("Interaction design", "".join(rows).replace(" ││ ", ""))

    def test_colors_stay_out_of_logs_and_respect_no_color(self):
        terminal = StringIO()
        terminal.isatty = lambda: True
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict("os.environ", {}, clear=True), redirect_stdout(terminal), console_log(root):
                show_panel("[MODEL OUTPUT]", "Response content", tone="output")
            self.assertIn("\x1b[", terminal.getvalue())
            self.assertNotIn("\x1b[", (root / "compiler.log").read_text())
        terminal.seek(0)
        terminal.truncate()
        with patch.dict("os.environ", {"NO_COLOR": "1"}), redirect_stdout(terminal):
            show_panel("[MODEL OUTPUT]", "Response content", tone="output")
        self.assertNotIn("\x1b[", terminal.getvalue())

    def test_waiting_heartbeat_includes_activity_and_elapsed_time(self):
        model = self.model(lambda request: httpx.Response(200, json=self.response('{"ok":true}')))
        terminal = StringIO()
        # Trigger one heartbeat without making the suite wait ten seconds.
        with redirect_stdout(terminal), patch("infrastructure.utils.presentation.model_io.Event") as event:
            event.return_value.wait.side_effect = [False, True]
            invoke(model.client, {"model": model.name, "messages": [{"role": "user", "content": "Generate."}]})
        self.assertIn("elapsed (including transport retries)", terminal.getvalue())


if __name__ == "__main__":
    unittest.main()
