"""Common agent identity, prompt construction and structured model execution."""

from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.agent import AgentLogger


class BaseAgent:
    """Build task prompts and request a JSON result through the shared model client."""

    def __init__(self, model_name: str | None = None, *,
            json_mode: bool = True) -> None:
        self.model = TextModel(model_name=model_name, json_mode=json_mode)
        self.logger = AgentLogger(type(self).__name__)
        self.model.logger = self.logger

    def build_system_prompt(self) -> str:
        """Return agent instructions; specialized agents can override this method."""
        return ""

    def build_user_prompt(self, input: dict) -> dict:
        """Build task data, which the model transport serializes as the user message."""
        return ""

    def run(self) -> dict:
        """Construct both prompts and return the parsed JSON response."""
        pass
