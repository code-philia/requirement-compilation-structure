# File input benchmarks

Run manually from the compiler directory. Ordinary unit test discovery never makes live requests.

```bash
# Count input files and inspect the matrix without API requests.
uv run python tests/test_token_input/run.py --dry-run

# Run using the input directory configured in config.json.
uv run python tests/test_token_input/run.py

# Select another directory; each file is a separate request input.
uv run python tests/test_token_input/run.py --input-dir /path/to/inputs --repeats 1

# Use a separate configuration and result path.
uv run python tests/test_token_input/run.py --config tests/test_token_input/config.local.json --output /tmp/benchmark.jsonl
```

## Input files

Set `"input_dir": "input"` in `config.json`. Relative configuration paths resolve against the configuration file's directory; relative `--input-dir` paths resolve against the current working directory. The default directory is `tests/test_token_input/input/`, which contains a small replaceable example file.

The runner recursively reads every visible file as UTF-8 text, measures each file by character count, and prints the full inventory before requests. Files are sorted by character count, then relative filename. Each model processes files from smallest to largest and sends each file once by default. Files are sent individually, without truncating or combining them. Hidden files and hidden directories are excluded. Unreadable or non-UTF-8 files cause an error before any API requests.

File text is the user message. A short system instruction asks the model to read it and reply only `OK`. A UTF-8 BOM is removed; line endings are otherwise preserved. Token counts come only from server-reported usage; no local tokenizer is used. Repeated requests send identical text and may benefit from prompt caching.

## Providers and keys

`providers` is an expandable list; each provider has its own base URL, key, and model list. Existing keys and model settings are independent of the input directory.

```json
{
  "input_dir": "input",
  "repeats": 1,
  "timeout_seconds": 300,
  "providers": [
    {
      "name": "provider-a",
      "base_url": "https://your-provider.example/v1",
      "api_key": "replace-with-this-provider-key",
      "models": ["model-a", "model-b"],
      "request_options": {}
    }
  ]
}
```

Alternatively, `api_key_env` names an environment variable loaded from the process environment or compiler `.env`. When both are provided, `api_key` takes precedence. Optional `base_url_env` overrides `base_url` with an environment variable's value.

The HTTP client uses `trust_env=False`, bypassing environment proxies (`HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY`, including lowercase variants). It also ignores environment certificate settings such as `SSL_CERT_FILE`. Provider credentials and `base_url_env` configuration still apply.

Requests use the OpenAI-compatible `/chat/completions` protocol. Optional `request_options` can supply provider-specific settings such as `extra_body`. Requests do not set an output token limit; the provider and model defaults apply. No automatic retries or parameter fallbacks are performed. Each repetition measures one full non-streaming SDK request, including provider queue time and receiving the complete response. It does not measure time to first token. Request errors do not stop subsequent cases; any failed case makes the process exit with status 1. Missing credentials fail before requests begin.

## Final comparison and results

Each case prints round-trip latency, usage input tokens, cached input tokens, output tokens, and total tokens. Missing fields display `unavailable`. Errors include their type, message, HTTP status, body, and underlying transport cause when available.

The final output pivots results into six comparison tables: success counts, round-trip latency, input tokens, cached input tokens, output tokens, and total tokens. Files are mapped to compact IDs (`F1`, `F2`, ...) once above the tables so long file names do not widen every table. Each row is an input file (smallest first); each column is a provider/model. Multiple models from the same provider remain separate, so their measurements are not mixed.

```text
Round-trip latency (seconds)
File      | Characters | provider-a/model-a | provider-b/model-b
----------+--------------+--------------------+-------------------
F1        | 8,000        | 1.250              | 2.100
F2        | 64,000       | 4.300              | N/A
```

Values come from successful requests only. If repetitions are explicitly enabled, each cell is an average of reported values; the default is one request. Missing usage or failed requests display `N/A`; the success table distinguishes failure from missing data. Output tokens come directly from usage `completion_tokens` (or `output_tokens`). Cached input is part of input and is not added to total again. Detailed errors appear after the tables.

Existing JSONL results can be compared without making new requests or loading provider credentials:

```bash
uv run python tests/test_token_input/run.py --summarize tests/test_token_input/results/YOUR_RESULT.jsonl
```

Results are appended immediately to `results/<UTC timestamp>.jsonl` (or `--output`), with each row containing the file name, character count, full original usage, normalized counts, elapsed time, identifiers, choices, and error details. Input file contents and API keys are not logged. Configured keys are redacted from error text. The final comparison is also saved beside the results as `<stem>.summary.txt`.
