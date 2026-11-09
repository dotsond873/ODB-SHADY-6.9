"""Provider contracts and deterministic multi-model routing."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


class ModelProvider(Protocol):
    """A model adapter must expose a stable name and a text completion method."""

    name: str

    def complete(self, *, system_prompt: str, messages: list[dict[str, str]]) -> str:
        ...


@dataclass
class ModelRouter:
    """Routes a request to a selected provider or an ordered fallback chain."""

    providers: Sequence[ModelProvider]

    def __post_init__(self) -> None:
        if not self.providers:
            raise ValueError("At least one model provider must be configured.")
        names = [provider.name for provider in self.providers]
        if len(names) != len(set(names)):
            raise ValueError("Provider names must be unique.")

    @property
    def available_models(self) -> list[str]:
        return [provider.name for provider in self.providers]

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        preferred: str | None = None,
    ) -> str:
        ordered = list(self.providers)
        if preferred:
            selected = [provider for provider in ordered if provider.name == preferred]
            if not selected:
                raise ValueError(f"Unknown model provider: {preferred}")
            ordered = selected + [p for p in ordered if p.name != preferred]

        failures: list[str] = []
        for provider in ordered:
            try:
                answer = provider.complete(
                    system_prompt=system_prompt,
                    messages=messages,
                )
                if not isinstance(answer, str) or not answer.strip():
                    raise RuntimeError("Provider returned an empty response.")
                return answer.strip()
            except Exception as exc:
                failures.append(f"{provider.name}: {type(exc).__name__}: {exc}")

        raise RuntimeError(
            "All configured model providers failed. " + " | ".join(failures)
        )
