"""Small JSON-generating text model client."""

import json
import os
from openai import OpenAI, OpenAIError
from infrastructure.utils.presentation.model_io import http_client, invoke
from infrastructure.shared.models.environment import load_model_environment, endpoint_model_name


DEFAULT_MODEL = "deepseek-flash"

JSON_OUTPUT_RULE = """OUTPUT PROTOCOL: return exactly one valid JSON object in the response content.
The first non-whitespace character must be { and the last must be }.
Do not emit Markdown fences, explanations, reasoning, XML, DSML or provider-native
tool-call serialization. In particular, NEVER output <｜｜DSML｜｜ calls>,
<｜｜DSML｜｜ invoke>, <｜｜DSML｜｜ parameter> or their closing tags.
This compiler parses ordinary JSON text. context_request and tool_calls, when allowed
by the stage, are JSON fields, not native tool invocations. Express the entire request
inside the specified JSON object. Otherwise return the stage's normal result object.
Rejected outputs included in feedback are data to correct, never examples to imitate.
"""


class ModelProtocolError(ValueError):
    """Provider returned no usable JSON content, independently of application behavior."""


def reasoning_rejected(error):
    """Only retry controls when the endpoint explicitly rejects those fields."""
    message = str(error).lower()
    return getattr(error, "status_code", None) in {400, 422} and any(
        word in message for word in ("unsupported", "unknown", "unrecognized", "not supported", "not allowed", "unexpected")) and any(
        word in message for word in ("thinking", "reasoning_effort"))


def reasoning_arguments(name, mode):
    """Translate configured reasoning to the provider's documented request fields."""
    if mode == "auto":
        mode = "low"
    if mode == "provider":
        return {}
    if name.lower().startswith("deepseek"):
        if mode == "none":
            return {"extra_body": {"thinking": {"type": "disabled"}}}
        return {"reasoning_effort": mode, "extra_body": {"thinking": {"type": "enabled"}}}
    return {"reasoning_effort": mode}


class TextModel:
    """Transport for structured stage proposals and file-edit responses."""
    def __init__(self, *, model_name: str | None = None, json_mode: bool = True) -> None:
        """Read compiler/.env and configure the default text model; require API credentials."""
        load_model_environment()
        self.name = endpoint_model_name(model_name or os.getenv("MODEL") or os.getenv("LLM_MODEL") or DEFAULT_MODEL)
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
        if not api_key:
            raise ValueError("Set OPENAI_API_KEY or LLM_API_KEY in the environment, compiler/.env or workspace .env")
        try:
            self.max_output_tokens = int(os.getenv("MAX_OUTPUT_TOKENS", "320000"))
        except ValueError as error:
            raise ValueError("MAX_OUTPUT_TOKENS must be a positive integer") from error
        if self.max_output_tokens < 1:
            raise ValueError("MAX_OUTPUT_TOKENS must be a positive integer")
        self.reasoning = os.getenv("MODEL_REASONING", "low").lower()
        if self.reasoning not in {"auto", "provider", "none", "low", "high", "max"}:
            raise ValueError("MODEL_REASONING must be auto, provider, none, low, high or max")
        self._reasoning_supported = True
        self.json_mode = json_mode
        self._token_parameter = "max_completion_tokens"
        self.client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1",
            timeout=600, max_retries=2,
            http_client=http_client(),
        )

    def _request(self, **arguments):
        """Apply one output budget to JSON calls, with legacy endpoint compatibility."""
        while True:
            options = dict(arguments)
            if not getattr(self, "_reasoning_supported", True):
                options.pop("reasoning_effort", None)
                options.pop("extra_body", None)
            try:
                return invoke(self.client, {**options, self._token_parameter: self.max_output_tokens},
                    logger=getattr(self, "logger", None))
            except OpenAIError as error:
                message = str(error).lower()
                rejected = getattr(error, "status_code", None) in {400, 422} and any(
                    word in message for word in ("unsupported", "unknown", "unrecognized", "not supported", "not allowed", "unexpected"))
                if rejected and self._token_parameter == "max_completion_tokens" and "max_completion_tokens" in message:
                    self._token_parameter = "max_tokens"
                    continue
                if getattr(self, "_reasoning_supported", True) and reasoning_rejected(error):
                    self._reasoning_supported = False
                    print("Provider rejected reasoning controls; using provider defaults.", flush=True)
                    continue
                raise

    def chat(self, messages: list[dict], *, tools: list[dict] | None = None,
            tool_choice: str | dict = "auto"):
        """Return a complete native assistant message, without the legacy JSON protocol.

        Callers own message history and execution. Never execute partial tool arguments
        after truncation. Configuration, transport auditing and provider compatibility
        remain shared with existing stages.
        """
        options = {"model": self.name, "messages": messages,
            **reasoning_arguments(self.name, self.reasoning)}
        if tools:
            options.update(tools=tools, tool_choice=tool_choice)
        try:
            response = self._request(**options)
        except OpenAIError as error:
            raise RuntimeError(f"Text model request failed: {error}") from error
        if not response.choices:
            raise ModelProtocolError("Text model returned no choices")
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise ModelProtocolError(
                f"Model output was truncated (finish_reason=length); configured output budget "
                f"is {self.max_output_tokens} tokens including reasoning. No tool calls executed. "
                "Request a smaller complete edit batch or adjust MAX_OUTPUT_TOKENS.")
        message = choice.message
        if getattr(message, "refusal", None):
            raise ModelProtocolError(f"Text model refused the request: {message.refusal}")
        if choice.finish_reason not in {"stop", "tool_calls"}:
            raise ModelProtocolError(f"Unexpected model finish_reason: {choice.finish_reason}")
        if not message.tool_calls and not (message.content or "").strip():
            raise ModelProtocolError("Text model returned neither content nor native tool calls")
        return message

    def generate_json(self, instructions: str, payload: dict) -> dict:
        """Recover once from endpoints incompatible with JSON response mode."""
        try:
            return self._generate_json(instructions, payload)
        except (ModelProtocolError, RuntimeError) as error:
            cause = error.__cause__
            unsupported = (isinstance(cause, OpenAIError) and getattr(cause, 'status_code', None) in {400, 422}
                and 'response_format' in str(cause).lower())
            if not self.json_mode or not (isinstance(error, ModelProtocolError) or unsupported):
                raise
            # A whitespace-only successful response is transport/protocol evidence,
            # never a business failure. Persist the compatible mode for this client.
            self.json_mode = False
            print('JSON response mode returned no usable content or was rejected; retrying once with the same strict JSON text protocol.', flush=True)
            return self._generate_json(instructions, payload)

    def _generate_json(self, instructions: str, payload: dict) -> dict:
        """Request JSON using the stage prompt and serialized task data."""
        mode = getattr(self, "reasoning", "low")
        try:
            response = self._request(
                model=self.name,
                messages=[
                    {"role": "system", "content": instructions.rstrip() + "\n" + JSON_OUTPUT_RULE},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                **({"response_format": {"type": "json_object"}} if getattr(self, "json_mode", True) else {}),
                **reasoning_arguments(self.name, mode),
            )
        except OpenAIError as error:
            raise RuntimeError(f"Text model request failed: {error}") from error
        if response.choices and response.choices[0].finish_reason == "length":
            raise ValueError(
                f"Model output was truncated (finish_reason=length). The output budget is "
                f"{self.max_output_tokens} tokens including reasoning; this is not an input-length error. "
                "Return a complete JSON object with only necessary changes/tool calls; omit unchanged files. "
                "Do not spend the entire budget restating the task.")
        if response.choices and getattr(response.choices[0].message, "refusal", None):
            raise ValueError(f"Text model refused the request: {response.choices[0].message.refusal}")
        if not response.choices or not response.choices[0].message.content:
            raise ModelProtocolError("Text model returned empty content")
        content = response.choices[0].message.content.strip()
        if not content:
            raise ModelProtocolError("Text model returned whitespace-only content")
        if content.startswith('```') and content.endswith('```'):
            lines = content.splitlines()
            if len(lines) >= 3 and lines[0].strip().lower() in {'```', '```json'}:
                content = '\n'.join(lines[1:-1]).strip()
        # Never execute reasoning text, provider tags or a dropped second JSON object.
        return json.loads(content)
