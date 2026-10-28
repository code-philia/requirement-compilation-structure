"""Small JSON-generating text model client."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError


class TextModel:
    """Transport for structured stage proposals and one-action-at-a-time agent calls."""
    def __init__(self) -> None:
        """Read compiler/.env and configure the text model client; reject missing credentials or model name."""
        load_dotenv(Path(__file__).resolve().parents[3] / ".env")
        self.name = os.getenv("MODEL")
        api_key = os.getenv("OPENAI_API_KEY")
        if not self.name or not api_key:
            raise ValueError("Set MODEL and OPENAI_API_KEY in compiler/.env")
        try:
            self.max_output_tokens = int(os.getenv("MAX_OUTPUT_TOKENS", "32768"))
        except ValueError as error:
            raise ValueError("MAX_OUTPUT_TOKENS must be a positive integer") from error
        if self.max_output_tokens < 1:
            raise ValueError("MAX_OUTPUT_TOKENS must be a positive integer")
        self._token_parameter = "max_completion_tokens"
        self.client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
            timeout=120, max_retries=2,
        )

    def _request(self, **arguments):
        """Apply one output budget to JSON and tool calls, with legacy endpoint compatibility."""
        try:
            response = self.client.chat.completions.create(
                **arguments, **{self._token_parameter: self.max_output_tokens},
            )
        except OpenAIError as error:
            # Some compatible endpoints only support the older max_tokens name.
            # Retry only an explicit parameter rejection, not arbitrary failures.
            message = str(error).lower()
            unsupported = any(word in message for word in ("unsupported", "unknown", "unrecognized", "not supported", "not allowed", "unexpected"))
            if self._token_parameter != "max_completion_tokens" or getattr(error, "status_code", None) not in {400, 422} or "max_completion_tokens" not in message or not unsupported:
                raise
            self._token_parameter = "max_tokens"
            response = self.client.chat.completions.create(
                **arguments, max_tokens=self.max_output_tokens,
            )
        # Detect transport truncation before attempting to parse partial JSON.
        if response.choices and response.choices[0].finish_reason == "length":
            raise ValueError(
                f"Model output was truncated (finish_reason=length; MAX_OUTPUT_TOKENS={self.max_output_tokens}). "
                "Increase MAX_OUTPUT_TOKENS if the model supports a larger budget, or request a smaller incremental response."
            )
        return response

    def generate_json(self, instructions: str, payload: dict) -> dict:
        """Request one ordinary JSON object; stage code owns examples and structural/semantic validation."""
        try:
            response = self._request(
                model=self.name,
                messages=[
                    {"role": "system", "content": instructions.rstrip() + "\nReturn exactly one JSON object without Markdown."},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
            )
        except OpenAIError as error:
            raise RuntimeError(f"Text model request failed: {error}") from error
        if response.choices and getattr(response.choices[0].message, "refusal", None):
            raise ValueError(f"Text model refused the request: {response.choices[0].message.refusal}")
        if not response.choices or not response.choices[0].message.content:
            raise ValueError("Text model returned empty content")
        result = json.loads(response.choices[0].message.content)
        if not isinstance(result, dict):
            raise ValueError("Text model must return a JSON object")
        return result

    def generate_action(self, instructions: str, payload: dict, definitions: list[dict]) -> dict:
        """Use one native function call; retain JSON fallback for older endpoints."""
        if getattr(self, "_tool_mode", "native") == "json":
            return self.generate_json(instructions, payload)
        try:
            response = self._request(
                model=self.name,
                messages=[
                    {"role": "system", "content": instructions + "\nCall exactly one provided tool."},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                tools=definitions, tool_choice="required", parallel_tool_calls=False,
            )
        except OpenAIError as error:
            # Capability fallback is explicit and remembered for this session.
            if getattr(error, "status_code", None) in {400, 404, 422} and any(word in str(error).lower() for word in ("tools", "tool_choice", "parallel_tool_calls", "function calling")):
                self._tool_mode = "json"
                return self.generate_json(instructions, payload)
            raise RuntimeError(f"Agent model request failed: {error}") from error
        calls = response.choices[0].message.tool_calls if response.choices else None
        if not calls or len(calls) != 1:
            raise ValueError("Expected exactly one native tool call")
        return {"tool": calls[0].function.name, "arguments": json.loads(calls[0].function.arguments)}
