"""Approval-aware, resumable execution of explicit task plans.

Plans contain only registered tool names and JSON arguments. This coordinator
never generates shell commands or executes arbitrary model-provided code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .approvals import ApprovalStore
from .permissions import ActionRisk
from .tasks import PlannedStep, StepStatus, Task, TaskStatus, TaskStore
from .tools import ToolExecutor


@dataclass(frozen=True)
class TaskProgress:
    task: Task
    state: str
    message: str
    approval_id: str | None = None
    step_result: str | None = None


class TaskCoordinator:
    """Advance one tool step at a time, pausing for human approval."""

    def __init__(self, store: TaskStore, executor: ToolExecutor,
                 approvals: ApprovalStore) -> None:
        self.store = store
        self.executor = executor
        self.approvals = approvals

    def create(self, title: str, steps: Sequence[PlannedStep]) -> Task:
        # Validate the complete plan before saving any of it.
        for step in steps:
            tool = self.executor.registry.get(step.tool_name)
            args = dict(step.arguments)
            unknown = set(args) - tool.allowed_arguments
            missing = tool.required_arguments - set(args)
            if unknown or missing:
                raise ValueError(
                    f"Invalid arguments for {tool.name}. Missing: {sorted(missing)}; "
                    f"unknown: {sorted(unknown)}"
                )
        return self.store.create_task(title, steps)

    def run_next(self, task_id: str) -> TaskProgress:
        task = self.store.get_task(task_id)
        if task.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED}:
            return TaskProgress(task, task.status.value, "Task is not runnable.")
        step = next((item for item in task.steps
                     if item.status not in {StepStatus.COMPLETED, StepStatus.CANCELLED}), None)
        if step is None:
            return TaskProgress(task, "completed", "All steps completed.")
        if step.status is StepStatus.WAITING_APPROVAL:
            return TaskProgress(task, "waiting_approval",
                                "Waiting for explicit user approval.",
                                approval_id=step.approval_id)

        tool = self.executor.registry.get(step.tool_name)
        if tool.risk is not ActionRisk.READ_ONLY:
            approval_id = self.executor.request_approval(tool.name)
            self.store.set_step(step.id, StepStatus.WAITING_APPROVAL,
                                approval_id=approval_id)
            return TaskProgress(self.store.get_task(task_id), "waiting_approval",
                                f"Approval required before: {step.description or tool.name}",
                                approval_id=approval_id)
        return self._execute_step(task_id, step)

    def approve_and_run(self, task_id: str, approval_id: str, *,
                        user_confirmed: bool) -> TaskProgress:
        """Call only after an authenticated UI receives explicit user confirmation."""
        if not user_confirmed:
            raise PermissionError("Explicit user confirmation is required.")
        task = self.store.get_task(task_id)
        step = next((item for item in task.steps if item.approval_id == approval_id), None)
        if step is None or step.status is not StepStatus.WAITING_APPROVAL:
            raise ValueError("Approval does not match a waiting step in this task.")
        if not self.approvals.approve(approval_id):
            raise ValueError("Approval is no longer pending.")
        return self._execute_step(task_id, step, approval_id=approval_id)

    def deny(self, task_id: str, approval_id: str, *,
             user_confirmed: bool) -> Task:
        if not user_confirmed:
            raise PermissionError("Explicit user confirmation is required.")
        task = self.store.get_task(task_id)
        step = next((item for item in task.steps if item.approval_id == approval_id), None)
        if step is None or step.status is not StepStatus.WAITING_APPROVAL:
            raise ValueError("Approval does not match a waiting step in this task.")
        if not self.approvals.deny(approval_id):
            raise ValueError("Approval is no longer pending.")
        self.store.set_step(step.id, StepStatus.FAILED, error_type="ApprovalDenied")
        return self.store.get_task(task_id)

    def cancel(self, task_id: str, *, user_confirmed: bool) -> Task:
        if not user_confirmed:
            raise PermissionError("Explicit user confirmation is required.")
        return self.store.cancel_task(task_id)

    def _execute_step(self, task_id: str, step: object,
                      approval_id: str | None = None) -> TaskProgress:
        try:
            result = self.executor.execute(step.tool_name, step.arguments,
                                           approval_id=approval_id)
        except Exception as exc:
            self.store.set_step(step.id, StepStatus.FAILED,
                                error_type=type(exc).__name__)
            return TaskProgress(self.store.get_task(task_id), "failed",
                                f"Step failed: {type(exc).__name__}")
        summary = str(result)[:500]
        self.store.set_step(step.id, StepStatus.COMPLETED, result_summary=summary)
        updated = self.store.get_task(task_id)
        state = "completed" if updated.status is TaskStatus.COMPLETED else "step_completed"
        return TaskProgress(updated, state, "Step completed.", step_result=summary)
