import json

import pytest

from shady.openai_compatible import OpenAICompatibleProvider
from shady.provider_config import build_router_from_env


def test_provider_sends_chat_payload_and_parses_answer():
    captured = {}

    def transport(url, headers, body, timeout):
        captured.update(url=url, headers=headers, payload=json.loads(body), timeout=timeout)
        return b'{"choices":[{"message":{"content":"  Hello from Shady.  "}}]}'

    provider = OpenAICompatibleProvider(
        name="test", model="test-model", api_key="secret-token",
        base_url="https://example.test/v1", timeout=12, transport=transport,
    )
    answer = provider.complete(
        system_prompt="You are Shady.",
        messages=[{"role": "user", "content": "Hello"}],
    )

    assert answer == "Hello from Shady."
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["payload"]["model"] == "test-model"
    assert captured["payload"]["messages"] == [
        {"role": "system", "content": "You are Shady."},
        {"role": "user", "content": "Hello"},
    ]
    assert captured["timeout"] == 12


def test_provider_rejects_invalid_message_role():
    provider = OpenAICompatibleProvider(
        name="test", model="m", api_key="secret", transport=lambda *args: b"{}"
    )
    with pytest.raises(ValueError, match="roles"):
        provider.complete(system_prompt="system", messages=[{"role": "system", "content": "no"}])


def test_provider_does_not_expose_http_error_body():
    from urllib.error import HTTPError

    def fail(*args):
        raise HTTPError("https://example.test", 401, "unauthorized", {}, None)

    provider = OpenAICompatibleProvider(
        name="test", model="m", api_key="never-print-this", transport=fail
    )
    with pytest.raises(RuntimeError, match="HTTP 401") as error:
        provider.complete(system_prompt="system", messages=[])
    assert "never-print-this" not in str(error.value)


def test_provider_rejects_malformed_response():
    provider = OpenAICompatibleProvider(
        name="test", model="m", api_key="secret", transport=lambda *args: b"not-json"
    )
    with pytest.raises(RuntimeError, match="invalid"):
        provider.complete(system_prompt="system", messages=[])


def test_environment_factory_requires_credentials():
    with pytest.raises(ValueError, match="SHADY_API_KEY"):
        build_router_from_env({})


def test_environment_factory_builds_router_without_network():
    router = build_router_from_env({
        "SHADY_API_KEY": "secret",
        "SHADY_MODEL": "test-model",
        "SHADY_API_BASE_URL": "https://compatible.example/v1",
    }, transport=lambda *args: b'{"choices":[{"message":{"content":"ready"}}]}')
    assert router.available_models == ["groq"]
    assert router.complete(system_prompt="system", messages=[]) == "ready"
