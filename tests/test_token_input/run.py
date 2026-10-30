"""Explicit, sequential live benchmarks for OpenAI-compatible Chat Completions APIs."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from statistics import mean
from time import perf_counter
import unicodedata

from dotenv import load_dotenv
import httpx
from openai import OpenAI


HERE = Path(__file__).resolve().parent
SYSTEM = "Read the supplied file content. Reply with only OK."


def load_inputs(directory):
    """Read each visible UTF-8 file separately and sort by its character count."""
    if not directory.is_dir():
        raise ValueError(f"Input directory does not exist: {directory}")
    inputs = []
    for path in directory.rglob("*"):
        relative = path.relative_to(directory)
        if not path.is_file() or any(part.startswith(".") for part in relative.parts):
            continue
        try:
            content = path.read_bytes().decode("utf-8-sig")
        except (OSError, UnicodeError) as error:
            raise ValueError(f"Cannot read UTF-8 input file {relative}: {error}") from error
        inputs.append({"file": relative.as_posix(), "content": content,
            "input_characters": len(content)})
    if not inputs:
        raise ValueError(f"No visible input files found in: {directory}")
    return sorted(inputs, key=lambda item: (item["input_characters"], item["file"]))


def table(headers, rows):
    """Align terminal columns, including wide file names, without extra dependencies."""
    rows = [[str(value).replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        for value in row] for row in [headers, *rows]]

    def width(value):
        return sum(0 if unicodedata.combining(char) else
            2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in value)

    widths = [max(width(row[i]) for row in rows) for i in range(len(headers))]
    lines = [" | ".join(value + " " * (widths[i] - width(value)) for i, value in enumerate(row)) for row in rows]
    lines.insert(1, "-+-".join("-" * size for size in widths))
    return "\n".join(lines)


def final_summary(records):
    """Pivot each metric by provider/model, with input files ordered by local size."""
    groups = {}
    files = {}
    columns = list(dict.fromkeys((record["provider"], record["base_url"], record["model"]) for record in records))
    for record in records:
        key = (record["file"], record["provider"], record["base_url"], record["model"])
        groups.setdefault(key, []).append(record)
        files[record["file"]] = record.get("input_characters", 0)
    labels = [f"{provider}/{model}" for provider, _, model in columns]
    if len(set(labels)) != len(labels):
        labels = [f"{provider}/{model} ({url})" for provider, url, model in columns]
    headers = ["File", "Characters", *labels]
    sections = ["\nFinal comparison by provider/model"]
    ordered_files = sorted(files, key=lambda name: (files[name], name))
    aliases = {name: f"F{index}" for index, name in enumerate(ordered_files, 1)}
    sections.append("Input files:\n" + "\n".join(f"{aliases[name]} = {name}" for name in ordered_files))
    metrics = [("Success (OK/all)", None), ("Round-trip latency (seconds)", "round_trip_seconds"),
        ("Input tokens (usage)", "input_tokens"), ("Cached input tokens (usage)", "cached_input_tokens"),
        ("Output tokens (usage)", "output_tokens"), ("Total tokens (usage)", "total_tokens")]
    for title, field in metrics:
        rows = []
        for file in ordered_files:
            row = [aliases[file], f"{files[file]:,}"]
            for column in columns:
                attempts = groups.get((file, *column), [])
                successful = [record for record in attempts if record["status"] == "ok"]
                if field is None:
                    value = f"{len(successful)}/{len(attempts)}" if attempts else "N/A"
                else:
                    values = [record[field] for record in successful if isinstance(record.get(field), (int, float))]
                    if values:
                        precision = 3 if field == "round_trip_seconds" else 1 if len(values) > 1 else 0
                        value = f"{mean(values):,.{precision}f}"
                    else:
                        value = "N/A"
                row.append(value)
            rows.append(row)
        sections.append(title + "\n" + table(headers, rows))
    sections.append("Values are from successful requests only; repeated runs are averaged. "
        "N/A = no reported value or no successful request. Cached input is included in input.")
    for record in records:
        if record["status"] == "error":
            sections.append(f"ERROR [{record['provider']}/{record['model']}] {record['file']} #{record['repeat']}: " + record["error_message"])
    return "\n\n".join(sections)


def usage_counts(usage):
    """Normalize common usage names while retaining the full original usage separately."""
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached = details.get("cached_tokens")
    return {
        "input_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
        "cached_input_tokens": cached if cached is not None else usage.get("prompt_cache_hit_tokens"),
        "output_tokens": usage.get("completion_tokens", usage.get("output_tokens")),
        "total_tokens": usage.get("total_tokens"),
    }


def provider_key(provider):
    """Prefer a directly configured key, falling back to an environment variable."""
    return provider.get("api_key") or os.getenv(provider.get("api_key_env", ""))


def run_case(client, model, messages, options):
    """Time exactly one non-streaming SDK request; SDK retries are disabled by the caller."""
    started = perf_counter()
    try:
        response = client.chat.completions.create(model=model, messages=messages, **options)
        elapsed = perf_counter() - started
        raw = response.model_dump(mode="json")
        usage = raw.get("usage") or {}
        return {
            "status": "ok", "round_trip_seconds": elapsed,
            "response_id": response.id, "response_model": response.model,
            "request_id": getattr(response, "_request_id", None),
            "usage": usage, **usage_counts(usage),
            "choices": raw.get("choices", []),
        }
    except Exception as error:
        return {
            "status": "error", "round_trip_seconds": perf_counter() - started,
            "error_type": type(error).__name__, "error_message": str(error),
            "http_status": getattr(error, "status_code", None),
            "request_id": getattr(error, "request_id", None),
            "error_body": getattr(error, "body", None),
            "error_cause": str(error.__cause__) if error.__cause__ else None,
        }


def display(record):
    label = f"[{record['provider']}/{record['model']}] {record['file']} ({record['input_characters']:,} characters) #{record['repeat']}"
    if record["status"] == "planned":
        return f"{label} | planned | user text: {record['input_characters']:,} characters"
    elapsed = record["round_trip_seconds"]
    if record["status"] == "error":
        return f"{label} | ERROR | RTT {elapsed:.3f}s\n" + json.dumps(
            {key: value for key, value in record.items() if key.startswith("error_") or key == "http_status"},
            ensure_ascii=False, indent=2, default=str)
    counts = " | ".join(f"{key}: {record.get(key) if record.get(key) is not None else 'unavailable'}"
        for key in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens"))
    return f"{label} | OK | RTT {elapsed:.3f}s | {counts}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summarize", type=Path, help="Print comparison tables from existing JSONL results without API calls")
    parser.add_argument("--config", type=Path, default=HERE / "config.json")
    parser.add_argument("--output", type=Path, help="JSONL output path (default: results/<timestamp>.jsonl)")
    parser.add_argument("--input-dir", type=Path, help="Directory containing UTF-8 input files (recursive)")
    parser.add_argument("--repeats", type=int, help="Override repetitions per file")
    parser.add_argument("--dry-run", action="store_true", help="Print the request matrix without API calls or keys")
    args = parser.parse_args(argv)
    if args.summarize:
        try:
            records = [json.loads(line) for line in args.summarize.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, ValueError) as error:
            parser.error(f"Cannot read results: {error}")
        if not records:
            parser.error("No results to summarize")
        summary = final_summary(records)
        print(summary, flush=True)
        summary_path = args.summarize.with_suffix(".summary.txt")
        summary_path.write_text(summary + "\n", encoding="utf-8")
        print(f"Comparison tables: {summary_path}", flush=True)
        return 0
    load_dotenv(HERE.parents[1] / ".env", encoding="utf-8-sig")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    repeats = args.repeats if args.repeats is not None else config.get("repeats", 1)
    if repeats < 1:
        parser.error("Repetitions must be positive")
    directory = args.input_dir or args.config.resolve().parent / config.get("input_dir", "input")
    try:
        inputs = load_inputs(directory)
    except ValueError as error:
        parser.error(str(error))
    providers = config["providers"]
    if not providers or any(not provider.get("models") for provider in providers):
        parser.error("Configure at least one provider and one model per provider")
    if not args.dry_run:
        missing = [provider["name"] for provider in providers if not provider_key(provider)]
        if missing:
            parser.error("Missing API key for providers (set api_key or api_key_env): " + ", ".join(sorted(set(missing))))
    secrets = [provider_key(provider) for provider in providers]

    def redact(text):
        for secret in secrets:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return text

    output = args.output or HERE / "results" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".jsonl")
    if not args.dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)
    requests = len(inputs) * repeats * sum(len(provider["models"]) for provider in providers)
    print(redact("Input files (ascending character count):\n" + table(
        ["File", "Characters"], [[item["file"], f"{item['input_characters']:,}"] for item in inputs])), flush=True)
    print(f"Requests: {requests} | retries: 0 | streaming: false", flush=True)
    failures = 0
    completed = 0
    records = []
    for provider in providers:
        base_url = os.getenv(provider.get("base_url_env", "")) or provider["base_url"]
        options = provider.get("request_options", {})
        if {"model", "messages", "stream"} & options.keys():
            parser.error("request_options must not override model, messages, or stream")
        # Dry runs never construct a client or send requests.
        client = None if args.dry_run else OpenAI(
            base_url=base_url, api_key=provider_key(provider),
            timeout=httpx.Timeout(config.get("timeout_seconds", 300), connect=30), max_retries=0,
            http_client=httpx.Client(trust_env=False),
        )
        try:
            for model in provider["models"]:
                for item in inputs:
                    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": item["content"]}]
                    for repeat in range(1, repeats + 1):
                        label = f"[{provider['name']}/{model}] {item['file']} ({item['input_characters']:,} characters) #{repeat}"
                        if client:
                            print(redact(label + " | requesting..."), flush=True)
                        record = {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "provider": provider["name"], "base_url": base_url, "model": model,
                            "file": item["file"], "input_directory": str(directory.resolve()),
                            "input_characters": item["input_characters"],
                            "repeat": repeat, "request_options": options,
                            **(run_case(client, model, messages, options) if client else {"status": "planned"}),
                        }
                        print(redact(display(record)), flush=True)
                        if not args.dry_run:
                            records.append(record)
                            with output.open("a", encoding="utf-8") as log:
                                log.write(redact(json.dumps(record, ensure_ascii=False, default=str)) + "\n")
                            completed += 1
                            failures += record["status"] == "error"
        finally:
            if client:
                client.close()
    if not args.dry_run:
        summary = redact(final_summary(records))
        print(summary, flush=True)
        summary_path = output.with_suffix(".summary.txt")
        summary_path.write_text(summary + "\n", encoding="utf-8")
        print(f"Completed: {completed} | errors: {failures} | results: {output}", flush=True)
        print(f"Comparison table: {summary_path}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
