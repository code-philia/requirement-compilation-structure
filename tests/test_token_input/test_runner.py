"""Verify the benchmark over mock HTTP transport without paid API requests."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI

from tests.test_token_input import run


class TokenInputBenchmark(unittest.TestCase):
    def test_input_files_are_counted_sorted_and_preserved(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'nested').mkdir()
            (root / 'a-large.txt').write_text('Hello world! ' * 100)
            (root / 'nested/small.txt').write_bytes('中文\r\nhello'.encode())
            (root / '.hidden').write_text('ignored')
            inputs = run.load_inputs(root)
        self.assertEqual([item['file'] for item in inputs], ['nested/small.txt', 'a-large.txt'])
        self.assertEqual(inputs[0]['content'], '中文\r\nhello')
        for item in inputs:
            self.assertEqual(item['input_characters'], len(item['content']))

    def test_matrix_records_errors_and_continues_without_retrying(self):
        requests = []

        def handler(request):
            expected_key = "test-key-second" if request.url.host == "second.test" else "test-key-first"
            self.assertEqual(request.headers["authorization"], f"Bearer {expected_key}")
            requests.append(json.loads(request.content))
            self.assertNotIn("max_tokens", requests[-1])
            self.assertNotIn("max_completion_tokens", requests[-1])
            if len(requests) == 1:
                return httpx.Response(400, json={"error": {
                    "message": "Input too large; test-key-first", "type": "context_length_exceeded"}})
            return httpx.Response(200, json={
                "id": "test", "object": "chat.completion", "created": 0, "model": "actual-model",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "OK"}}],
                "usage": {"prompt_tokens": 100, "prompt_cache_hit_tokens": 80,
                    "completion_tokens": 1, "total_tokens": 101},
            })

        def client(**kwargs):
            original = kwargs.pop('http_client')
            self.assertFalse(original.trust_env)
            original.close()
            return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler), trust_env=False))

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            (root / 'input').mkdir()
            (root / 'input/large.txt').write_text('record ' * 100)
            (root / 'input/small.txt').write_text('hello')
            config.write_text(json.dumps({"input_dir": "input", "repeats": 3, "providers": [
                {"name": "first", "base_url": "https://first.test/v1", "api_key_env": "TEST_FIRST_KEY", "models": ["a", "b"]},
                {"name": "second", "base_url": "https://second.test/v1", "api_key": "test-key-second", "models": ["c"]},
            ]}))
            output = root / "results.jsonl"
            terminal = StringIO()
            with patch.object(run, "OpenAI", side_effect=client), patch.object(run, "load_dotenv"), patch.dict(
                "os.environ", {"TEST_FIRST_KEY": "test-key-first", "TEST_SECOND_KEY": "test-key-second"}
            ), redirect_stdout(terminal):
                status = run.main(["--config", str(config), "--output", str(output)])
            rows = [json.loads(line) for line in output.read_text().splitlines()]
            summary = output.with_suffix('.summary.txt').read_text()
        self.assertEqual(status, 1)
        self.assertEqual(len(requests), 18)
        self.assertEqual(len(rows), 18)
        self.assertEqual(rows[0]["http_status"], 400)
        self.assertIn("context_length_exceeded", json.dumps(rows[0]["error_body"]))
        self.assertEqual(rows[-1]["provider"], "second")
        self.assertEqual(rows[-1]["cached_input_tokens"], 80)
        self.assertEqual(rows[-1]["output_tokens"], 1)
        self.assertTrue(all(row["round_trip_seconds"] >= 0 for row in rows))
        self.assertEqual(requests[0]["messages"], requests[1]["messages"])
        self.assertEqual([row['file'] for row in rows[:6]], ['small.txt'] * 3 + ['large.txt'] * 3)
        self.assertEqual(requests[0]['messages'][1]['content'], 'hello')
        self.assertNotIn("test-key-first", json.dumps(rows) + terminal.getvalue())
        self.assertIn("[REDACTED]", terminal.getvalue())
        self.assertIn('Final comparison', summary)
        self.assertIn('Output tokens (usage)', summary)
        self.assertIn('2/3', summary)
        self.assertIn('first/a', summary)
        self.assertIn('second/c', summary)

    def test_dry_run_never_requires_keys_or_constructs_client(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            (root / 'input').mkdir()
            (root / 'input/example.txt').write_text('hello')
            config.write_text(json.dumps({"input_dir": "input", "providers": [
                {"name": "test", "base_url": "https://test.invalid/v1", "api_key_env": "ABSENT_KEY", "models": ["a"]},
            ]}))
            output = root / "results.jsonl"
            terminal = StringIO()
            with patch.object(run, "OpenAI") as client, patch.object(run, "load_dotenv"), redirect_stdout(terminal):
                self.assertEqual(run.main(["--config", str(config), "--output", str(output), "--dry-run"]), 0)
            client.assert_not_called()
            self.assertFalse(output.exists())
            self.assertEqual(terminal.getvalue().count("| planned |"), 1)

    def test_summary_handles_missing_usage_all_errors_and_average_output(self):
        base = {'file': 'file.txt', 'provider': 'test', 'base_url': 'https://test.invalid', 'model': 'm',
            'input_characters': 10, 'repeat': 1, 'round_trip_seconds': 2.0}
        records = [{**base, 'status': 'ok', 'output_tokens': 2},
            {**base, 'status': 'ok', 'output_tokens': 6},
            {**base, 'model': 'failed', 'status': 'error', 'error_message': 'context limit'}]
        summary = run.final_summary(records)
        self.assertIn('4.0', summary)
        self.assertIn('0/1', summary)
        self.assertIn('N/A', summary)
        self.assertIn('context limit', summary)

    def test_empty_and_binary_input_directories_fail_before_requests(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, 'No visible input files'):
                run.load_inputs(root)
            (root / 'binary.bin').write_bytes(b'\xff\xfe')
            with self.assertRaisesRegex(ValueError, 'Cannot read UTF-8 input file'):
                run.load_inputs(root)

    def test_saved_results_produce_provider_columns_without_api_calls(self):
        records = [
            {'file': file, 'input_characters': size, 'provider': provider, 'model': 'model',
                'base_url': 'https://' + provider, 'status': 'ok', 'round_trip_seconds': latency,
                'output_tokens': output, 'repeat': 1}
            for file, size in [('large.txt', 100), ('small.txt', 10)]
            for provider, latency, output in [('first', 1.5, 12), ('second', 2.5, 24)]
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'results.jsonl'
            path.write_text('\n'.join(json.dumps(record) for record in records))
            terminal = StringIO()
            with patch.object(run, 'OpenAI') as client, redirect_stdout(terminal):
                self.assertEqual(run.main(['--summarize', str(path)]), 0)
            client.assert_not_called()
            result = path.with_suffix('.summary.txt').read_text()
        self.assertIn('first/model', result)
        self.assertIn('second/model', result)
        self.assertIn('1.500', result)
        self.assertIn('2.500', result)
        self.assertIn('Output tokens (usage)', result)
        self.assertLess(result.index('small.txt'), result.index('large.txt'))

    def test_usage_supports_both_cache_formats_and_missing_values(self):
        self.assertEqual(run.usage_counts({})["cached_input_tokens"], None)
        self.assertEqual(run.usage_counts({"prompt_tokens_details": {"cached_tokens": 0},
            "prompt_cache_hit_tokens": 8})["cached_input_tokens"], 0)
        self.assertEqual(run.usage_counts({"input_tokens": 20, "output_tokens": 2,
            "input_tokens_details": {"cached_tokens": 10}})["cached_input_tokens"], 10)

    def test_direct_api_key_takes_precedence_over_environment(self):
        with patch.dict("os.environ", {"TEST_KEY": "from-env"}):
            self.assertEqual(run.provider_key({"api_key": "direct", "api_key_env": "TEST_KEY"}), "direct")
            self.assertEqual(run.provider_key({"api_key_env": "TEST_KEY"}), "from-env")


if __name__ == "__main__":
    unittest.main()
