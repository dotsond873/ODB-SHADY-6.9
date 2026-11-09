"""OpenAI-compatible chat-completions adapter using only the standard library."""
from __future__ import annotations

import json
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


Transport = Callable[[str, dict[str, str], bytes, float], bytes]


def _urllib_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return response.read()


class OpenAICompatibleProvider:
    """Connects to a chat-completions endpoint compatible with the OpenAI API shape.

    Works with hosted providers and compatible self-hosted endpoints. This adapter
    does not imply that a particular vendor or model is included or free.
    """

    def __init__(
        self,
        *,
        name: str,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 45.0,
        transport: Transport | None = None,
    ) -> None:
        if not name.strip():
            raise ValueError("Provider name is required.")
        if not model.strip():
            raise ValueError("Model name is required.")
        if not api_key.strip():
            raise ValueError("API key is required.")
        if timeout <= 0:
            raise ValueError("Timeout must be greater than zero.")
        self.name = name.strip()
        self.model = model.strip()
        self._api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport or _urllib_transport

    def complete(self, *, system_prompt: str, messages: list[dict[str, str]]) -> str:
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ValueError("System prompt cannot be empty.")
        normalized: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for item in messages:
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                raise ValueError("Messages must contain user or assistant roles.")
            content = item.get("content")
            if not isinstance(content, str):
                raise ValueError("Message content must be text.")
            normalized.append({"role": item["role"], "content": content})

        payload = json.dumps({"model": self.model, "messages": normalized}).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            raw = self._transport(
                f"{self.base_url}/chat/completions", headers, payload, self.timeout
            )
        except HTTPError as exc:
            raise RuntimeError(f"Model provider returned HTTP {exc.code}.") from None
        except URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, TimeoutError):
                raise TimeoutError("Model provider request timed out.") from None
            raise RuntimeError("Could not reach the model provider.") from None
        except TimeoutError:
            raise TimeoutError("Model provider request timed out.") from None
        except Exception as exc:
            raise RuntimeError(
                f"Model provider transport failed ({type(exc).__name__})."
            ) from None

        try:
            data = json.loads(raw.decode("utf-8"))
            answer = data["choices"][0]["message"]["content"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError):
            raise RuntimeError("Model provider returned an invalid chat-completions response.") from None
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("Model provider returned an empty response.")
        return answer.strip()
