import json
import uuid

from shady.approvals import ApprovalStore
from shady.audit import AuditLog
from shady.memory import MemoryStore
from shady.providers import ModelRouter
from shady.tasks import TaskStore
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


def test_long_multibyte_message_fits_the_http_body_limit():
    import json

    from serve import MAX_BODY

    message = "話" * ShadyAPI.MAX_MESSAGE_CHARS
    payload = {"message": message, "session_id": str(uuid.uuid4())}
    # Browsers send raw UTF-8; some clients escape every non-ASCII character.
    for encoded in (json.dumps(payload, ensure_ascii=False), json.dumps(payload)):
        assert len(encoded.encode("utf-8")) <= MAX_BODY


def test_memories_require_the_owner_token(tmp_path):
    api = make_api(tmp_path)
    assert api.list_memories("wrong")[0] == 401
    assert api.add_memory(None, {"content": "hello"})[0] == 401
    assert api.delete_memory("wrong", {"id": 1})[0] == 401


def test_memories_can_be_saved_listed_and_deleted(tmp_path):
    api = make_api(tmp_path)
    token = "a" * 40
    status, result = api.add_memory(token, {"content": "The lab is in Detroit"})
    assert status == 201
    memory_id = result["memory"]["id"]
    status, result = api.list_memories(token)
    assert status == 200
    assert [item["content"] for item in result["memories"]] == ["The lab is in Detroit"]
    assert api.delete_memory(token, {"id": memory_id})[0] == 200
    assert api.list_memories(token)[1]["memories"] == []
    assert api.delete_memory(token, {"id": memory_id})[0] == 404


def test_memory_input_is_validated(tmp_path):
    api = make_api(tmp_path)
    token = "a" * 40
    assert api.add_memory(token, {"content": "   "})[0] == 400
    assert api.add_memory(token, {"content": "x" * (api.MAX_MEMORY_CHARS + 1)})[0] == 413
    assert api.delete_memory(token, {"id": "one"})[0] == 400


def test_access_token_must_be_long(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="32 characters"):
        ShadyAPI(access_token="short", router=ModelRouter([StubProvider()]))


class PlannerProvider:
    name = "planner"

    def __init__(self, plan):
        self.plan = plan

    def complete(self, *, system_prompt, messages):
        return json.dumps(self.plan)


def make_code_api(tmp_path, plan):
    database = tmp_path / "code.sqlite3"
    return ShadyAPI(
        access_token="a" * 40,
        router=ModelRouter([PlannerProvider(plan)]),
        memory=MemoryStore(tmp_path / "memories.sqlite3"),
        approvals=ApprovalStore(database),
        audit=AuditLog(database),
        tasks=TaskStore(database),
    )


def test_models_endpoint_lists_configured_providers(tmp_path):
    api = make_api(tmp_path)
    assert api.models("wrong")[0] == 401
    status, result = api.models("a" * 40)
    assert status == 200
    assert result == {"models": ["stub"]}


def test_code_task_waits_for_approval_before_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("SHADY_WORKSPACE", str(tmp_path / "workspace"))
    plan = {
        "title": "Write hello",
        "steps": [{
            "tool_name": "write_file",
            "arguments": {"path": "hello.py", "content": "print('hi')"},
            "description": "Create hello.py",
        }],
    }
    api = make_code_api(tmp_path, plan)
    token = "a" * 40

    status, result = api.create_task(token, {"request": "write hello.py"})
    assert status == 201
    task_id = result["task"]["id"]
    assert result["task"]["steps"][0]["tool_name"] == "write_file"

    status, step = api.run_task_step(token, {"task_id": task_id})
    assert status == 200
    assert step["state"] == "waiting_approval"
    approval_id = step["task"]["steps"][0]["approval_id"]
    assert approval_id
    assert not (tmp_path / "workspace" / "hello.py").exists()

    status, done = api.approve_task(
        token, {"task_id": task_id, "approval_id": approval_id}
    )
    assert status == 200
    assert done["state"] == "completed"
    assert (tmp_path / "workspace" / "hello.py").read_text() == "print('hi')"


def test_code_task_rejects_unknown_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("SHADY_WORKSPACE", str(tmp_path / "workspace"))
    plan = {
        "title": "Bad plan",
        "steps": [{
            "tool_name": "rm_rf",
            "arguments": {},
            "description": "Delete everything",
        }],
    }
    status, result = make_code_api(tmp_path, plan).create_task(
        "a" * 40, {"request": "delete everything"}
    )
    assert status == 422
    assert "unregistered" in result["error"]


def test_code_task_requires_the_owner_token(tmp_path):
    api = make_api(tmp_path)
    assert api.create_task("wrong", {"request": "write a file"})[0] == 401
    assert api.run_task_step("wrong", {"task_id": "x"})[0] == 401
    assert api.list_tasks("wrong")[0] == 401
