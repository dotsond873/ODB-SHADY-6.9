"""Provider-neutral orchestration shell; no model vendor is assumed."""

from collections.abc import Callable
from typing import Any

from .identity import build_system_prompt


class ShadyEngine:
    """Minimal core that can be connected to a model provider adapter."""

    def __init__(self, provider: Callable[..., str] | None = None) -> None:
        self.provider = provider

    @property
    def system_prompt(self) -> str:
        return build_system_prompt()

    def ask(self, message: str, **context: Any) -> str:
        if not message or not message.strip():
            raise ValueError("Message cannot be empty.")
        if self.provider is None:
            raise RuntimeError(
                "No model provider is configured yet. Add and configure a provider adapter."
            )
        return self.provider(
            system_prompt=self.system_prompt,
            message=message,
            **context,
        )
