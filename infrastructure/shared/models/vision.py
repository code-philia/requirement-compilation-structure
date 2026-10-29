"""Minimal visual model client using the existing model environment variables."""

import base64
import json
import mimetypes
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError
from infrastructure.utils.presentation.model_io import http_client, invoke


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
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=120, max_retries=2, http_client=http_client())

    def analyze(self, image: Path) -> dict:
        """Send one supported reference image and validate the returned layout, elements, and style evidence."""
        mime = mimetypes.guess_type(image.name)[0]
        if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise ValueError(f"Unsupported image format: {image.name}")
        encoded = base64.b64encode(image.read_bytes()).decode("ascii")
        # --- Extension point: visual evidence extraction ----------------------
        # Compare prompts or structured visual representations here. Keep the
        # {layout, elements, style} contract aligned with validation below.
        prompt = (
            "Analyze this UI reference image using visible evidence only. "
            "Do not infer business rules or hidden interactions. "
            "Return a JSON object in English with exactly these fields: "
            "layout (string: regions, alignment, and relative positions), "
            "elements (array of strings: visible controls, original labels, options, and states), "
            "style (string: colors, typography, borders, spacing, and other visual details). "
            "Preserve visible labels in their original language. "
            "Explicitly identify anything illegible; do not invent details."
        )
        try:
            response = invoke(self.client, {
                "model": self.name,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{mime};base64,{encoded}", "detail": "high",
                    }},
                ]}],
                "response_format": {"type": "json_object"},
            })
        except OpenAIError as error:
            raise RuntimeError(f"Visual model request failed ({image.name}): {error}") from error
        if not response.choices or not response.choices[0].message.content:
            raise ValueError(f"Visual model returned empty content: {image.name}")
        result = json.loads(response.choices[0].message.content)
        if (
            not isinstance(result, dict) or not {"layout", "elements", "style"}.issubset(result)
            or not isinstance(result["layout"], str)
            or not isinstance(result["style"], str)
            or not isinstance(result["elements"], list)
            or not all(isinstance(item, str) for item in result["elements"])
        ):
            raise ValueError(f"Visual analysis fields do not match the expected format: {image.name}")
        return result
