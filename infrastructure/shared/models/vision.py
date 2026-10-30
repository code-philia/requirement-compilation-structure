"""Minimal visual model client using the existing model environment variables."""

import base64
import json
from io import BytesIO
import mimetypes
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError
from PIL import Image, ImageOps
from infrastructure.utils.presentation.model_io import http_client, invoke
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.models.text import JSON_OUTPUT_RULE, reasoning_arguments, reasoning_rejected


VISION_INSTRUCTIONS = """Describe the supplied UI reference using visible evidence only.
Return {"layout":"...", "elements":["..."], "style":"..."}.
layout describes regions, alignment and relative positions; elements lists visible
controls, labels, options and states; style describes colors, typography and spacing.
Write descriptions in English while quoting visible labels in their original language.
Identify illegible or uncertain details instead of inventing them. Do not infer hidden
business behavior, APIs, database fields or interactions from appearance alone.
"""

VISUAL_REPAIR_PREFIX = "Correct the previous response:\n"

def compress_image(data: bytes, mime: str) -> tuple[bytes, str]:
    """Resize static references to 2048px and encode JPEG, retaining smaller originals."""
    with Image.open(BytesIO(data)) as source:
        if getattr(source, "is_animated", False):
            return data, mime
        image = ImageOps.exif_transpose(source)
        original_size = image.size
        image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        # Composite transparency against white so transparent UI text stays readable.
        rgba = image.convert("RGBA")
        rgb = Image.new("RGB", rgba.size, "white")
        rgb.paste(rgba, mask=rgba.getchannel("A"))
        buffer = BytesIO()
        rgb.save(buffer, format="JPEG", quality=85, subsampling=0)
        compressed = buffer.getvalue()
        if len(compressed) < len(data) or image.size != original_size:
            return compressed, "image/jpeg"
    return data, mime


class VisualModel:
    """Extract visible image evidence without inferring hidden business behavior."""
    def __init__(self) -> None:
        """Read compiler/.env and configure the image-capable model, falling back to text-model settings."""
        load_dotenv(Path(__file__).resolve().parents[3] / ".env", encoding="utf-8-sig")
        self.name = os.getenv("VISUAL_MODEL") or os.getenv("MODEL")
        api_key = os.getenv("VISUAL_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("VISUAL_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        if not self.name or not api_key:
            raise ValueError("Set MODEL and OPENAI_API_KEY in compiler/.env; the model must accept images")
        self.reasoning = os.getenv("VISUAL_REASONING", os.getenv("MODEL_REASONING", "auto")).lower()
        if self.reasoning not in {"auto", "provider", "none", "low", "high", "max"}:
            raise ValueError("VISUAL_REASONING must be auto, provider, none, low, high or max")
        self._reasoning_supported = True
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=600, max_retries=2, http_client=http_client())

    def analyze(self, image: Path, max_attempts: int = 5) -> dict:
        """Send one supported reference image and parse the returned layout, elements, and style evidence."""
        mime = mimetypes.guess_type(image.name)[0]
        if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise ValueError(f"Unsupported image format: {image.name}")
        original = image.read_bytes()
        compressed, mime = compress_image(original, mime)
        print(f"Image compression: {image.name} | {len(original) / 1024:.1f} -> {len(compressed) / 1024:.1f} KiB", flush=True)
        encoded = base64.b64encode(compressed).decode("ascii")
        result, _ = propose_json(self, VISION_INSTRUCTIONS, {"image_url": f"data:{mime};base64,{encoded}"},
            lambda value: value, DemoConsole(), f"Visual analysis {image.name}", max_attempts)
        return result

    def generate_json(self, instructions: str, payload: dict) -> dict:
        """Request visual JSON and include prior response errors when repairing it."""
        text = instructions.rstrip() + "\n" + JSON_OUTPUT_RULE
        if "correction" in payload:
            text += "\n" + VISUAL_REPAIR_PREFIX + json.dumps(payload["correction"], ensure_ascii=False)
        mode = getattr(self, "reasoning", "auto")
        if mode == "auto":
            mode = "none" if self.name.lower().startswith("deepseek") else "provider"
        arguments = {
                "model": self.name,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": payload["image_url"], "detail": "high"}},
                ]}],
                "response_format": {"type": "json_object"},
            }
        try:
            while True:
                controls = reasoning_arguments(self.name, mode) if getattr(self, "_reasoning_supported", True) else {}
                try:
                    response = invoke(self.client, {**arguments, **controls})
                    break
                except OpenAIError as error:
                    if not getattr(self, "_reasoning_supported", True) or not reasoning_rejected(error):
                        raise
                    self._reasoning_supported = False
                    print("Provider rejected reasoning controls; using provider defaults.", flush=True)
        except OpenAIError as error:
            raise RuntimeError(f"Visual model request failed: {error}") from error
        if not response.choices or not response.choices[0].message.content:
            raise ValueError("Visual model returned empty content")
        return json.loads(response.choices[0].message.content)
