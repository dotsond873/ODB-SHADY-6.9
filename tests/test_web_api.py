import uuid

from shady.memory import MemoryStore
from shady.providers import ModelRouter
from shady.web_api import ShadyAPI


class StubProvider:
    name = "stub"

    def complete(self, *, system_prompt, messages):
        return "Shady says: " + messages[-1]["content"]


def make_api(tmp_path):
    return ShadyAPI(
        access_token="a" * 40,
        router=ModelRouter([StubProvider()]),
        memory=MemoryStore(tmp_path / "web.sqlite3"),
    )


def test_health_does_not_expose_credentials(tmp_path):
    result = make_api(tmp_path).health()
    assert result == {
        "status": "ok",
        "service": "ODB SHADY 6.9",
        "model_configured": True,
    }
    assert "token" not in result


def test_chat_requires_owner_token(tmp_path):
    api = make_api(tmp_path)
    status, result = api.chat("wrong", {
        "message": "Hello", "session_id": str(uuid.uuid4())
    })
    assert status == 401
    assert result == {"error": "Authentication required."}


def test_chat_validates_session_and_returns_reply(tmp_path):
    api = make_api(tmp_path)
    session_id = str(uuid.uuid4())
    status, result = api.chat("a" * 40, {
        "message": "Hello Shady", "session_id": session_id
    })
    assert status == 200
    assert result["reply"] == "Shady says: Hello Shady"
    assert result["session_id"] == session_id


def test_chat_rejects_oversized_message_and_unknown_model(tmp_path):
    api = make_api(tmp_path)
    token = "a" * 40
    status, _ = api.chat(token, {
        "message": "x" * 6001, "session_id": str(uuid.uuid4())
    })
    assert status == 413
    status, result = api.chat(token, {
        "message": "Hello", "session_id": str(uuid.uuid4()),
        "preferred_model": "not-configured",
    })
    assert status == 400
    assert "not configured" in result["error"]


def test_access_token_must_be_long(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="32 characters"):
        ShadyAPI(access_token="short", router=ModelRouter([StubProvider()]))
