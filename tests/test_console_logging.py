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

from infrastructure.shared.models.text import TextModel, task_reasoning
from infrastructure.shared.models.vision import VisualModel
from infrastructure.utils.presentation.console import DemoConsole, preview, show_panel, display_width, WaitingStatus
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.presentation.model_io import _http_request, _http_response, _input_summary, _usage_summary, invoke


class ConsoleLogging(unittest.TestCase):
    """Run SDK serialization and retry handling without remote model requests."""

    def model(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False,
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

    def test_text_and_visual_clients_ignore_environment_proxies_and_keep_audit_hooks(self):
        with patch.dict("os.environ", {
            "OPENAI_API_KEY": "test-key", "MODEL": "test-model", "OPENAI_BASE_URL": "https://model.test/v1",
            "VISUAL_API_KEY": "test-key", "VISUAL_MODEL": "test-model", "VISUAL_BASE_URL": "https://model.test/v1",
            "HTTP_PROXY": "invalid-proxy", "HTTPS_PROXY": "invalid-proxy", "ALL_PROXY": "invalid-proxy",
            "http_proxy": "invalid-proxy", "https_proxy": "invalid-proxy", "all_proxy": "invalid-proxy",
        }):
            for model_type in (TextModel, VisualModel):
                with self.subTest(model=model_type.__name__):
                    model = model_type()
                    try:
                        transport = model.client._client
                        self.assertFalse(transport.trust_env)
                        self.assertEqual(transport.event_hooks["request"], [_http_request])
                        self.assertEqual(transport.event_hooks["response"], [_http_response])
                        self.assertEqual(model.client.timeout, 600)
                        self.assertEqual(model.client.max_retries, 2)
                    finally:
                        model.client.close()

    def test_console_is_bounded_but_panels_and_model_io_are_complete(self):
        source = "export const answer = 42;\n" * 1000 + "END-OF-SOURCE"
        raw_content = json.dumps({"edits": [{"path": "frontend/src/page.tsx", "content": source}]})
        model = self.model(lambda request: httpx.Response(200, json=self.response(raw_content)))
        terminal = StringIO()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("sys.argv", ["10_implement_ui.py"]), patch("infrastructure.utils.presentation.model_io.monotonic", side_effect=[10, 20, 25.125]), redirect_stdout(terminal), redirect_stderr(terminal), console_log(root):
                DemoConsole().show("PAGE-home | Input context", "INPUT-DETAIL\n" * 1000 + "END-OF-PANEL")
                result = model.generate_json("Implement UI.", {"files": {"page.tsx": {"content": source, "writable": True}}})
            records = [json.loads(line) for line in (root / "model_calls.jsonl").read_text().splitlines()]
            compiler_log = (root / "compiler.log").read_text()
            self.assertFalse((root / ".arc" / "model_logs").exists())
        self.assertEqual(result["edits"][0]["content"], source)
        self.assertNotIn("END-OF-PANEL", terminal.getvalue())
        self.assertNotIn("END-OF-SOURCE", terminal.getvalue())
        self.assertIn("END-OF-PANEL", compiler_log)
        self.assertIn("Stage 10", terminal.getvalue())
        self.assertIn("[WAITING]", terminal.getvalue())
        self.assertIn("frontend/src/page.tsx", terminal.getvalue())
        self.assertIn("export const answer = 42", terminal.getvalue())
        self.assertIn("truncated", terminal.getvalue())
        self.assertRegex(terminal.getvalue(), r"Input\s+│ 10")
        self.assertRegex(terminal.getvalue(), r"Cached input\s+│ unavailable")
        self.assertRegex(terminal.getvalue(), r"Output\s+│ 20")
        self.assertRegex(terminal.getvalue(), r"Round-trip latency\s+│ 5.12 s")
        self.assertIn("Round-trip latency: 5.12 s", compiler_log)
        self.assertEqual(records[3]["elapsed_seconds"], 5.125)
        self.assertNotIn("characters", terminal.getvalue())
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
            with patch("sys.argv", ["06_design_backend_apis.py"]), redirect_stdout(StringIO()), console_log(root, debug_model_io=True):
                self.assertEqual(model.generate_json("Generate.\nKeep line breaks.", {}), {"ok": True})
            records = [json.loads(line) for line in (root / "model_calls.jsonl").read_text().splitlines()]
            directory = root / ".arc" / "model_logs"
            inputs = list(directory.glob("*.model.input"))
            self.assertEqual(len(inputs), 3)
            self.assertEqual(len(list(directory.glob("*.model.ouput"))), 3)
            request_records = [record for record in records if record["event"] == "http_request"]
            response_records = [record for record in records if record["event"] == "http_response"]
            for index, (request_record, response_record) in enumerate(zip(request_records, response_records)):
                call_id = request_record["call_id"]
                attempt = 1 + sum(record["call_id"] == call_id for record in request_records[:index])
                input_file = next(directory.glob(f"06.*.{call_id[:8]}.{attempt}.model.input"))
                output_file = input_file.with_name(input_file.name.removesuffix(".input") + ".ouput")
                self.assertEqual(input_file.read_text(), "Generate.\nKeep line breaks.\nReturn exactly one JSON object without Markdown.\n\n{}")
                body = json.loads(response_record["body"])
                expected = body["error"]["message"] if "error" in body else body["choices"][0]["message"]["content"]
                self.assertEqual(output_file.read_text(), expected)
                self.assertNotIn("test-secret", input_file.read_text())
        requests = [json.loads(record["body"]) for record in records if record["event"] == "http_request"]
        self.assertEqual(requests, attempts)
        self.assertEqual(len(requests), 3)
        self.assertIn("max_completion_tokens", requests[0])
        self.assertIn("max_tokens", requests[2])
        self.assertEqual([record["status_code"] for record in records if record["event"] == "http_response"], [500, 400, 200])

    def test_reasoning_policy_and_actual_wire_controls(self):
        cases = [({}, "low"), ({"entity_name": "Note"}, "none"),
            ({"entity_name": "Note", "correction": {"error": "Invalid SQL response"}}, "low"),
            ({"task": {"test_path": None}}, "low"),
            ({"task": {"test_path": "backend/tests/save.test.ts"},
                "feedback": [{"error": "Fix test compilation"}]}, "low"),
            ({"task": {"test_path": "frontend/tests/e2e/save.spec.ts"},
                "feedback": [{"error": "Fix test assertions"}]}, "low"),
            ({"task": {}}, "none"),
            ({"task": {"api_id": "API-SAVE"}, "feedback": [{"error": "Compilation failed"}]}, "none"),
            ({"task": {"page": {"id": "home"}}, "feedback": [{"typecheck": {"returncode": 1}}]}, "none"),
            ({"task": {"triggers": {}}, "feedback": [{"e2e": {"returncode": 1}}]}, "none")]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                self.assertEqual(task_reasoning("deepseek-flash", "auto", payload), expected)
                self.assertEqual(task_reasoning("other-model", "auto", payload), "provider")
                self.assertEqual(task_reasoning("deepseek-flash", "high", payload), "high")
        attempts = []
        def handler(request):
            attempts.append(json.loads(request.content))
            return httpx.Response(200, json=self.response('{"ok":true}'))
        model = self.model(handler)
        model.name = "deepseek-flash"
        with redirect_stdout(StringIO()):
            model.generate_json("Implement", {"task": {}})
            model.generate_json("Design", {})
            model.generate_json("Generate tests", {"task": {"test_path": None}})
            model.generate_json("Repair tests", {"task": {"test_path": "test.ts"},
                "feedback": [{"error": "Fix test compilation"}]})
            for task in ({"api_id": "API-SAVE"}, {"page": {"id": "home"}}, {"triggers": {}}):
                model.generate_json("Repair implementation", {"task": task,
                    "feedback": [{"error": "Fix failed acceptance checks"}]})
        self.assertEqual(attempts[0]["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", attempts[0])
        self.assertEqual(attempts[1]["thinking"], {"type": "enabled"})
        self.assertEqual(attempts[1]["reasoning_effort"], "low")
        for request in attempts[2:4]:
            self.assertEqual(request["thinking"], {"type": "enabled"})
            self.assertEqual(request["reasoning_effort"], "low")
        for request in attempts[4:]:
            self.assertEqual(request["thinking"], {"type": "disabled"})
            self.assertNotIn("reasoning_effort", request)

    def test_unsupported_reasoning_falls_back_once_for_text_and_vision(self):
        for visual in (False, True):
            attempts = []
            def handler(request):
                body = json.loads(request.content)
                attempts.append(body)
                if "thinking" in body or "reasoning_effort" in body:
                    return httpx.Response(400, json={"error": {"message": "Unsupported parameter thinking"}})
                return httpx.Response(200, json=self.response('{"ok":true}'))
            model = self.model(handler)
            if visual:
                visual_model = VisualModel.__new__(VisualModel)
                visual_model.client = model.client
                model = visual_model
            model.name = "deepseek-flash"
            payload = {"image_url": "data:image/png;base64,QUJD"} if visual else {}
            with self.subTest(visual=visual), redirect_stdout(StringIO()):
                self.assertEqual(model.generate_json("Describe", payload), {"ok": True})
                self.assertEqual(model.generate_json("Describe", payload), {"ok": True})
                self.assertEqual(len(attempts), 3)
                self.assertNotIn("thinking", attempts[-1])
                self.assertNotIn("reasoning_effort", attempts[-1])

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

    def test_disabled_model_logging_keeps_usage_without_dumping_prompts_or_responses(self):
        marker = "PRIVATE-MODEL-OUTPUT"
        model = self.model(lambda request: httpx.Response(200, json=self.response(json.dumps({"secret": marker}))))
        terminal = StringIO()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with redirect_stdout(terminal), console_log(root, model_log=False, stage="06_design_backend_apis.py"):
                result = model.generate_json("PRIVATE-MODEL-PROMPT", {"task": "private"})
            self.assertEqual(result, {"secret": marker})
            logged = (root / "compiler.log").read_text()
            self.assertNotIn(marker, terminal.getvalue() + logged)
            self.assertNotIn("PRIVATE-MODEL-PROMPT", terminal.getvalue() + logged)
            self.assertFalse((root / "model_calls.jsonl").exists())
            self.assertFalse((root / ".arc" / "model_logs").exists())
        self.assertRegex(terminal.getvalue(), r"Input\s+│ 10")
        self.assertIn("Round-trip latency", terminal.getvalue())
        self.assertIn("Stage 06", terminal.getvalue())

    def test_missing_usage_has_no_local_estimate(self):
        summary = _usage_summary({})
        self.assertIn("input: unavailable", summary)
        self.assertIn("output: unavailable", summary)
        self.assertNotIn("~", summary)
        self.assertNotIn("estimate", summary)
        self.assertEqual(_usage_summary({"input_tokens": 1200, "output_tokens": 0, "total_tokens": 1200}),
            "Reported tokens | input: 1,200 | cached input: unavailable | output: 0 | total: 1,200")
        self.assertNotIn("tokens", _input_summary({"model": "test", "messages": [{"role": "user", "content": "Hello"}]}))

    def test_usage_cache_counts_survive_sdk_parsing_and_reach_logs(self):
        for extra, expected in [
            ({"prompt_tokens_details": {"cached_tokens": 0}}, "0"),
            ({"prompt_tokens_details": {"cached_tokens": 8}}, "8"),
            ({"prompt_cache_hit_tokens": 7}, "7"),
            ({"input_tokens_details": {"cached_tokens": 6}}, "6"),
        ]:
            with self.subTest(extra=extra), TemporaryDirectory() as temporary:
                body = self.response('{"ok":true}')
                body["usage"].update(extra)
                model = self.model(lambda request: httpx.Response(200, json=body))
                terminal = StringIO()
                root = Path(temporary)
                with redirect_stdout(terminal), console_log(root):
                    model.generate_json("Generate.", {})
                expected_line = f"Reported tokens | input: 10 | cached input: {expected} | output: 20 | total: 30"
                self.assertRegex(terminal.getvalue(), rf"Cached input\s+│ {expected}\s")
                self.assertIn(expected_line, (root / "compiler.log").read_text())

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
        self.assertIn("Interaction design", " ".join(" ".join(row.strip("│ ").split()) for row in rows))

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

    def test_redirected_waiting_message_is_printed_only_once(self):
        model = self.model(lambda request: httpx.Response(200, json=self.response('{"ok":true}')))
        terminal = StringIO()
        with redirect_stdout(terminal):
            invoke(model.client, {"model": model.name, "messages": [{"role": "user", "content": "Generate."}]})
        self.assertEqual(terminal.getvalue().count("[WAITING]"), 1)
        self.assertNotIn("\r", terminal.getvalue())

    def test_interactive_waiting_closes_idempotently_and_keeps_log_plain(self):
        terminal = StringIO()
        terminal.isatty = lambda: True
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with redirect_stdout(terminal), console_log(root):
                waiting = WaitingStatus()
                initial = terminal.getvalue()
                self.assertEqual(initial.count("[WAITING]"), 1)
                self.assertNotIn("elapsed", initial)
                waiting.close()
                cleared = terminal.getvalue()
                waiting.close()
                self.assertEqual(terminal.getvalue(), cleared)
            logged = (root / "compiler.log").read_bytes()
        redraws = [item for item in terminal.getvalue().split("\r") if "[WAITING]" in item]
        self.assertGreaterEqual(len(redraws), 1)
        self.assertEqual(logged.count(b"[WAITING]"), 1)
        self.assertNotIn(b"\r", logged)
        self.assertNotIn(b"\x1b[", logged)


if __name__ == "__main__":
    unittest.main()
