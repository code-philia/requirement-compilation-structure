"""One streaming model request, independent of compiler agents and retries."""

import json

import httpx


def normalize_usage(raw):
    def count(value):
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None

    input_tokens = count(raw.get("prompt_tokens", raw.get("input_tokens")))
    output_tokens = count(raw.get("completion_tokens", raw.get("output_tokens")))
    input_details = (
        raw.get("prompt_tokens_details") or raw.get("input_tokens_details") or {}
    )
    output_details = (
        raw.get("completion_tokens_details") or raw.get("output_tokens_details") or {}
    )
    cached = count(
        raw.get("prompt_cache_hit_tokens", input_details.get("cached_tokens"))
    )
    if input_tokens is None:
        missed = count(raw.get("prompt_cache_miss_tokens"))
        if missed is not None and cached is not None:
            input_tokens = missed + cached
    if cached is not None and input_tokens is not None:
        cached = min(cached, input_tokens)
    return {
        "input": input_tokens,
        "output": output_tokens,
        "cached": cached,
        "reasoning": count(output_details.get("reasoning_tokens")),
        "total": input_tokens + output_tokens
        if input_tokens is not None and output_tokens is not None
        else None,
    }


def estimate_cost(usage, price):
    if usage["input"] is None or usage["output"] is None:
        return None
    cached = usage["cached"] or 0
    cached_price = price["cached"]
    if cached_price is None:
        cached_price = price["input"]
    return (
        (usage["input"] - cached) * price["input"]
        + cached * cached_price
        + usage["output"] * price["output"]
    ) / 1_000_000


async def stream_model(base_url, api_key, request, timeout):
    async with httpx.AsyncClient(
        trust_env=False,
        timeout=httpx.Timeout(timeout, connect=20),
        follow_redirects=False,
    ) as client:
        async with client.stream(
            "POST",
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + api_key},
            json=request,
        ) as response:
            if response.is_error:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise ValueError(
                    f"模型服务返回 HTTP {response.status_code}：{body[:1200]}"
                )
            response.raise_for_status()
            if "application/json" in response.headers.get("content-type", ""):
                yield json.loads(await response.aread())
                return
            data_lines = []
            # SSE is UTF-8 regardless of the host locale or a gateway's charset.
            response.encoding = "utf-8"
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                    continue
                if line or not data_lines:
                    continue
                data = "\n".join(data_lines)
                data_lines = []
                if data == "[DONE]":
                    return
                yield json.loads(data)
            if data_lines:
                data = "\n".join(data_lines)
                if data != "[DONE]":
                    yield json.loads(data)


def response_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            part.get("text", "")
            for part in value
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""
