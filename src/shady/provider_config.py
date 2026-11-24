"""Environment-based configuration for an OpenAI-compatible model endpoint."""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Callable

from .openai_compatible import OpenAICompatibleProvider, Transport
from .providers import ModelRouter


def build_router_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    transport: Transport | None = None,
) -> ModelRouter:
    """Build a Gemini-first router with an optional legacy provider.

    Defaults target Groq Cloud. Required: SHADY_API_KEY and SHADY_MODEL.
    Optional: SHADY_API_BASE_URL, SHADY_PROVIDER_NAME, SHADY_TIMEOUT_SECONDS.
    """
    env = os.environ if environ is None else environ
    api_key = env.get("SHADY_API_KEY", "").strip()
    model = env.get("SHADY_MODEL", "openai/gpt-oss-120b").strip()
    gemini_key = env.get("GEMINI_API_KEY", "").strip()
    if not api_key and not gemini_key:
        raise ValueError("Set SHADY_API_KEY in the runtime environment.")
    if not model:
        raise ValueError("Set SHADY_MODEL in the runtime environment.")
    try:
        timeout = float(env.get("SHADY_TIMEOUT_SECONDS", "45"))
    except ValueError:
        raise ValueError("SHADY_TIMEOUT_SECONDS must be a number.") from None

    providers = []
    if gemini_key:
        providers.append(OpenAICompatibleProvider(
            name="gemini",
            model=env.get("GEMINI_MODEL", "gemini-2.5-flash").strip(),
            api_key=gemini_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            timeout=timeout,
            transport=transport,
        ))
    if api_key:
        provider = OpenAICompatibleProvider(
            name=env.get("SHADY_PROVIDER_NAME", "groq").strip() or "groq",
            model=model,
            api_key=api_key,
            base_url=env.get(
                "SHADY_API_BASE_URL", "https://api.groq.com/openai/v1"
            ).strip(),
            timeout=timeout,
            transport=transport,
        )
        if provider.name not in {p.name for p in providers}:
            providers.append(provider)
    return ModelRouter(providers)
