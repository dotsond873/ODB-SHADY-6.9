from shady.approvals import ApprovalStore
from shady.audit import AuditLog
from shady.permissions import ActionRisk
from shady.task_engine import TaskCoordinator
from shady.tasks import PlannedStep, StepStatus, TaskStatus, TaskStore
from shady.tools import ToolDefinition, ToolExecutor, ToolRegistry


def make_coordinator(tmp_path):
    db = tmp_path / "shady.sqlite3"
    approvals = ApprovalStore(db)
    audit = AuditLog(db)
    registry = ToolRegistry()
    calls = []
    registry.register(ToolDefinition(
        name="read_status", description="Read status", risk=ActionRisk.READ_ONLY,
        handler=lambda: calls.append("read") or "ready",
    ))
    registry.register(ToolDefinition(
        name="publish", description="Publish item", risk=ActionRisk.REVERSIBLE,
        handler=lambda item: calls.append(item) or "published",
        required_arguments=frozenset({"item"}),
        allowed_arguments=frozenset({"item"}),
    ))
    executor = ToolExecutor(registry, approvals, audit)
    store = TaskStore(db)
    return TaskCoordinator(store, executor, approvals), store, approvals, calls


def test_read_only_steps_run_and_complete(tmp_path):
    coordinator, store, _, calls = make_coordinator(tmp_path)
    task = coordinator.create("Check status", [PlannedStep("read_status", {})])
    progress = coordinator.run_next(task.id)
    assert progress.state == "completed"
    assert progress.task.status is TaskStatus.COMPLETED
    assert calls == ["read"]


def test_non_read_only_step_waits_for_approval_then_runs(tmp_path):
    coordinator, store, _, calls = make_coordinator(tmp_path)
    task = coordinator.create("Publish", [
        PlannedStep("publish", {"item": "draft-1"}, "Publish draft")
    ])
    waiting = coordinator.run_next(task.id)
    assert waiting.state == "waiting_approval"
    assert waiting.task.status is TaskStatus.WAITING_APPROVAL
    assert calls == []

    with pytest.raises(PermissionError):
        coordinator.approve_and_run(task.id, waiting.approval_id, user_confirmed=False)

    done = coordinator.approve_and_run(
        task.id, waiting.approval_id, user_confirmed=True
    )
    assert done.state == "completed"
    assert done.task.status is TaskStatus.COMPLETED
    assert calls == ["draft-1"]


def test_approval_is_bound_to_task_step_and_only_runs_once(tmp_path):
    coordinator, _, _, calls = make_coordinator(tmp_path)
    task = coordinator.create("Publish", [
        PlannedStep("publish", {"item": "draft-2"})
    ])
    waiting = coordinator.run_next(task.id)
    done = coordinator.approve_and_run(task.id, waiting.approval_id,
                                        user_confirmed=True)
    assert done.state == "completed"
    with pytest.raises(ValueError):
        coordinator.approve_and_run(task.id, waiting.approval_id,
                                    user_confirmed=True)
    assert calls == ["draft-2"]


def test_task_can_resume_after_read_only_step(tmp_path):
    coordinator, store, _, calls = make_coordinator(tmp_path)
    task = coordinator.create("Two steps", [
        PlannedStep("read_status", {}),
        PlannedStep("read_status", {}),
    ])
    first = coordinator.run_next(task.id)
    assert first.state == "step_completed"
    refreshed = store.get_task(task.id)
    assert refreshed.status is TaskStatus.RUNNING
    second = coordinator.run_next(task.id)
    assert second.state == "completed"
    assert calls == ["read", "read"]


def test_plan_validates_tools_before_persisting(tmp_path):
    coordinator, store, _, _ = make_coordinator(tmp_path)
    with pytest.raises(KeyError):
        coordinator.create("Bad plan", [PlannedStep("unknown_tool", {})])
    assert store.list_tasks() == []


def test_cancel_requires_confirmation(tmp_path):
    coordinator, _, _, _ = make_coordinator(tmp_path)
    task = coordinator.create("Cancel me", [PlannedStep("read_status", {})])
    with pytest.raises(PermissionError):
        coordinator.cancel(task.id, user_confirmed=False)
    cancelled = coordinator.cancel(task.id, user_confirmed=True)
    assert cancelled.status is TaskStatus.CANCELLED


import pytest
