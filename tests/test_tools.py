import pytest

from shady.approvals import ApprovalStore
from shady.audit import AuditLog
from shady.permissions import ActionRisk, ApprovalRequired
from shady.tools import ToolDefinition, ToolExecutor, ToolRegistry


def make_executor(tmp_path):
    db = tmp_path / "shady.sqlite3"
    registry = ToolRegistry()
    approvals = ApprovalStore(db)
    audit = AuditLog(db)
    return registry, approvals, audit, ToolExecutor(registry, approvals, audit)


def test_read_only_tool_executes_and_is_audited(tmp_path):
    registry, approvals, audit, executor = make_executor(tmp_path)
    registry.register(ToolDefinition(
        name="lookup_status",
        description="Return a status string",
        risk=ActionRisk.READ_ONLY,
        handler=lambda: "ready",
    ))

    assert executor.execute("lookup_status") == "ready"
    events = audit.recent()
    assert events[0]["status"] == "completed"
    assert events[0]["action_name"] == "lookup_status"


def test_write_tool_requires_approved_one_time_request(tmp_path):
    registry, approvals, audit, executor = make_executor(tmp_path)
    registry.register(ToolDefinition(
        name="save_note",
        description="Save a note",
        risk=ActionRisk.REVERSIBLE,
        handler=lambda note: f"saved:{note}",
        required_arguments=frozenset({"note"}),
        allowed_arguments=frozenset({"note"}),
    ))

    with pytest.raises(ApprovalRequired):
        executor.execute("save_note", {"note": "hello"})

    request_id = executor.request_approval("save_note")
    assert approvals.approve(request_id) is True
    assert executor.execute("save_note", {"note": "hello"}, approval_id=request_id) == "saved:hello"
    with pytest.raises(ApprovalRequired):
        executor.execute("save_note", {"note": "again"}, approval_id=request_id)


def test_approval_cannot_be_used_for_a_different_tool(tmp_path):
    registry, approvals, audit, executor = make_executor(tmp_path)
    for name in ("write_one", "write_two"):
        registry.register(ToolDefinition(
            name=name,
            description="Write action",
            risk=ActionRisk.CONSEQUENTIAL,
            handler=lambda: "ok",
        ))

    request_id = executor.request_approval("write_one")
    approvals.approve(request_id)
    with pytest.raises(ApprovalRequired):
        executor.execute("write_two", approval_id=request_id)


def test_denied_approval_cannot_be_consumed(tmp_path):
    registry, approvals, audit, executor = make_executor(tmp_path)
    registry.register(ToolDefinition(
        name="delete_item",
        description="Delete one item",
        risk=ActionRisk.DESTRUCTIVE,
        handler=lambda: "deleted",
    ))
    request_id = executor.request_approval("delete_item")
    assert approvals.deny(request_id) is True
    with pytest.raises(ApprovalRequired):
        executor.execute("delete_item", approval_id=request_id)


def test_unknown_and_invalid_arguments_are_rejected(tmp_path):
    registry, approvals, audit, executor = make_executor(tmp_path)
    registry.register(ToolDefinition(
        name="read_item",
        description="Read an item",
        risk=ActionRisk.READ_ONLY,
        handler=lambda item_id: item_id,
        required_arguments=frozenset({"item_id"}),
        allowed_arguments=frozenset({"item_id"}),
    ))
    with pytest.raises(KeyError, match="not allowlisted"):
        executor.execute("run_shell")
    with pytest.raises(ValueError, match="Invalid arguments"):
        executor.execute("read_item", {"item_id": "1", "command": "rm -rf /"})


def test_raw_arguments_are_not_written_to_audit_log(tmp_path):
    registry, approvals, audit, executor = make_executor(tmp_path)
    registry.register(ToolDefinition(
        name="read_secretish",
        description="Example tool",
        risk=ActionRisk.READ_ONLY,
        handler=lambda token: "ok",
        required_arguments=frozenset({"token"}),
        allowed_arguments=frozenset({"token"}),
    ))
    executor.execute("read_secretish", {"token": "DO_NOT_LOG_THIS"})
    assert "DO_NOT_LOG_THIS" not in str(audit.recent())
