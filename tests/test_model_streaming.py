"""The compiler sees complete ChatCompletion objects in either transport mode."""

import json
from collections.abc import Iterator

import httpx
import pytest
from openai import OpenAI

from infrastructure.shared.models.streaming import IncompleteModelStreamError, complete, streaming_enabled
from infrastructure.shared.models.text import TextModel
from infrastructure.shared.models.vision import VisualModel
from infrastructure.utils.presentation.model_io import _http_request, _http_response, invoke
from infrastructure.utils.presentation.logging import console_log


def event(delta, finish=None):
    return b"data: " + json.dumps({
        "id": "stream-1", "model": "test-model", "created": 1,
        "object": "chat.completion.chunk", "choices": [{
            "index": 0, "delta": delta, "finish_reason": finish,
        }],
    }).encode() + b"\n\n"


class SSE(httpx.SyncByteStream):
    def __init__(self, body, fail=False):
        self.body, self.fail, self.closed = body, fail, False

    def __iter__(self) -> Iterator[bytes]:
        for index in range(0, len(self.body), 17):
            yield self.body[index:index + 17]
        if self.fail:
            raise httpx.ReadError("connection lost")

    def close(self):
        self.closed = True


def client_for(sse, requests):
    def send(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, request=request, stream=sse, headers={
            "content-type": "text/event-stream",
        })
    return OpenAI(api_key="test-key", base_url="https://stream.invalid/v1", max_retries=0,
                  http_client=httpx.Client(transport=httpx.MockTransport(send),
                      event_hooks={"request": [_http_request], "response": [_http_response]}))


@pytest.mark.parametrize("switch,expected", [(None, False), ("0", False), ("1", True), ("true", True)])
def test_switch(monkeypatch, switch, expected):
    monkeypatch.delenv("LLM_STREAMING", raising=False)
    if switch is not None:
        monkeypatch.setenv("LLM_STREAMING", switch)
    assert streaming_enabled() is expected


def test_stream_preserves_content_reasoning_usage_and_logging(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_STREAMING", "1")
    sse = SSE(
        event({"role": "assistant", "reasoning_content": "think "})
        + event({"reasoning_content": "twice", "content": '{"name":'})
        + event({"content": '"张三"}'}) + event({}, "stop")
        + b'data: {"id":"stream-1","model":"test-model","created":1,'
          b'"object":"chat.completion.chunk","choices":[],"usage":{"prompt_tokens":8,'
          b'"completion_tokens":5,"total_tokens":13}}\n\ndata: [DONE]\n\n'
    )
    requests = []
    with client_for(sse, requests) as client, console_log(tmp_path, debug_model_io=True):
        response = invoke(client, {"model": "test-model", "messages": []})
    assert sse.closed
    assert len(requests) == 1
    assert requests[0]["stream"] is True
    assert requests[0]["stream_options"] == {"include_usage": True}
    assert response.choices[0].message.content == '{"name":"张三"}'
    assert response.choices[0].message.reasoning_content == "think twice"
    records = [json.loads(line) for line in (tmp_path / "model_calls.jsonl").read_text().splitlines()]
    assert [r["event"] for r in records] == ["request", "http_request", "http_response", "response"]
    assert records[-1]["response"]["usage"]["total_tokens"] == 13
    assert records[2]["streaming"] is True
    assert "test-key" not in json.dumps(records)
    outputs = list((tmp_path / ".arc/model_logs").glob("*.model.ouput"))
    assert len(outputs) == 1 and outputs[0].read_text() == '{"name":"张三"}'


def test_response_hook_does_not_consume_stream():
    sse = SSE(b"data: [DONE]\n\n")
    response = httpx.Response(200, request=httpx.Request("POST", "https://stream.invalid"),
                              headers={"content-type": "text/event-stream; charset=utf-8"}, stream=sse)
    _http_response(response)
    assert not response.is_stream_consumed
    response.close()


def test_tool_arguments_are_joined_without_parsing_partial_json():
    sse = SSE(event({"role": "assistant", "tool_calls": [{
        "index": 0, "id": "tool-1", "type": "function", "function": {
            "name": "submit", "arguments": '{"name":',
        },
    }]}) + event({"tool_calls": [{
        "index": 0, "function": {"arguments": '"张三"}'},
    }]}) + event({}, "tool_calls") + b"data: [DONE]\n\n")
    with client_for(sse, []) as client:
        response = complete(client, model="test-model", messages=[], stream=True)
    tool = response.choices[0].message.tool_calls[0]
    assert tool.id == "tool-1"
    assert tool.function.name == "submit"
    assert json.loads(tool.function.arguments) == {"name": "张三"}
    assert sse.closed


@pytest.mark.parametrize("ending", ["eof", "done_only", "length", "content_filter", "connection"])
def test_incomplete_stream_is_not_accepted_or_retried_as_non_streaming(ending, monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_STREAMING", "1")
    body = event({"role": "assistant", "content": '{"valid":"but partial"}'})
    if ending in {"length", "content_filter"}:
        body += event({}, ending)
    if ending in {"done_only", "length", "content_filter"}:
        body += b"data: [DONE]\n\n"
    sse = SSE(body, fail=ending == "connection")
    requests = []
    with client_for(sse, requests) as client:
        with pytest.raises(Exception):
            invoke(client, {"model": "test-model", "messages": []})
    assert sse.closed
    assert len(requests) == 1
    assert requests[0]["stream"] is True


def test_empty_stream_is_rejected():
    with client_for(SSE(b"data: [DONE]\n\n"), []) as client:
        with pytest.raises(IncompleteModelStreamError, match="empty"):
            complete(client, model="test-model", messages=[], stream=True)


def test_non_streaming_returns_original_response():
    requests = []

    def send(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "normal", "created": 1, "model": "test-model", "object": "chat.completion",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '{"ok":true}',
            }}],
        })

    with OpenAI(api_key="test-key", http_client=httpx.Client(
        transport=httpx.MockTransport(send),
    )) as client:
        response = complete(client, model="test-model", messages=[], stream=False)
    assert json.loads(response.choices[0].message.content) == {"ok": True}
    assert requests[0]["stream"] is False
    assert "stream_options" not in requests[0]


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("visual", [False, True])
def test_text_and_vision_keep_inputs_budget_reasoning_and_parameter_fallback(monkeypatch, streaming, visual):
    monkeypatch.setenv("LLM_STREAMING", "1" if streaming else "0")
    requests = []

    def send(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if "max_completion_tokens" in payload:
            return httpx.Response(400, request=request, json={"error": {
                "message": "Unsupported parameter max_completion_tokens", "type": "invalid_request_error",
            }})
        if streaming:
            return httpx.Response(200, request=request, headers={"content-type": "text/event-stream"},
                                 stream=SSE(event({"role": "assistant", "content": '{"ok":true}'})
                                            + event({}, "stop") + b"data: [DONE]\n\n"))
        return httpx.Response(200, request=request, json={
            "id": "normal", "created": 1, "model": "test-model", "object": "chat.completion",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '{"ok":true}',
            }}],
        })

    model = (VisualModel if visual else TextModel).__new__(VisualModel if visual else TextModel)
    model.name = "deepseek-test"
    model.reasoning = "none"
    model.max_output_tokens = 4096
    model._token_parameter = "max_completion_tokens"
    with OpenAI(api_key="test-key", max_retries=0, http_client=httpx.Client(
        transport=httpx.MockTransport(send),
        event_hooks={"request": [_http_request], "response": [_http_response]},
    )) as client:
        model.client = client
        payload = {"image_url": "data:image/png;base64,dGVzdA=="} if visual else {"question": "test"}
        assert model.generate_json("Generate.", payload) == {"ok": True}
    assert len(requests) == (1 if visual else 2)
    assert all(payload.get("stream", False) is streaming for payload in requests)
    assert all(payload["thinking"] == {"type": "disabled"} for payload in requests)
    assert all(payload["response_format"] == {"type": "json_object"} for payload in requests)
    if visual:
        assert requests[0]["messages"][0]["content"][1]["image_url"]["url"] == payload["image_url"]
    else:
        assert requests[-1]["max_tokens"] == 4096
