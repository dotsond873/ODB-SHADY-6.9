"""Allowlisted tool registry and permission-enforced execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .approvals import ApprovalStore
from .audit import AuditLog
from .permissions import ActionRisk, ApprovalRequired


ToolHandler = Callable[..., Any]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    risk: ActionRisk
    handler: ToolHandler
    required_arguments: frozenset[str] = frozenset()
    allowed_arguments: frozenset[str] = frozenset()


class ToolRegistry:
    """Explicit allowlist. Tools are registered by trusted application code."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if not definition.name or not definition.name.replace("_", "").isalnum():
            raise ValueError("Tool names may contain only letters, numbers, and underscores.")
        if definition.name in self._tools:
            raise ValueError(f"Tool already registered: {definition.name}")
        if not definition.required_arguments.issubset(definition.allowed_arguments):
            raise ValueError("Required arguments must also be allowed arguments.")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Tool is not allowlisted: {name}") from exc

    def describe(self) -> list[dict[str, str]]:
        return [
            {"name": item.name, "description": item.description, "risk": item.risk.name}
            for item in self._tools.values()
        ]


class ToolExecutor:
    """Validate, authorize, execute, and audit allowlisted tool calls."""

    def __init__(
        self,
        registry: ToolRegistry,
        approvals: ApprovalStore,
        audit: AuditLog,
    ) -> None:
        self.registry = registry
        self.approvals = approvals
        self.audit = audit

    def request_approval(self, tool_name: str) -> str:
        tool = self.registry.get(tool_name)
        if tool.risk is ActionRisk.READ_ONLY:
            raise ValueError("Read-only tools do not need an approval request.")
        approval_id = self.approvals.request(tool.name)
        self.audit.record(
            action_name=tool.name,
            risk=tool.risk.name,
            status="approval_requested",
            approval_id=approval_id,
        )
        return approval_id

    def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        approval_id: str | None = None,
    ) -> Any:
        tool = self.registry.get(tool_name)
        args = dict(arguments or {})
        unknown = set(args) - tool.allowed_arguments
        missing = tool.required_arguments - set(args)
        if unknown or missing:
            self.audit.record(
                action_name=tool.name,
                risk=tool.risk.name,
                status="invalid_arguments",
                details={
                    "unknown_arguments": sorted(unknown),
                    "missing_arguments": sorted(missing),
                },
            )
            raise ValueError(
                f"Invalid arguments. Missing: {sorted(missing)}; "
                f"unknown: {sorted(unknown)}"
            )

        if tool.risk is not ActionRisk.READ_ONLY:
            if not approval_id or not self.approvals.consume(approval_id, tool.name):
                self.audit.record(
                    action_name=tool.name,
                    risk=tool.risk.name,
                    status="approval_required",
                    approval_id=approval_id,
                )
                raise ApprovalRequired(
                    f"An approved, unused approval request is required for {tool.name}."
                )

        self.audit.record(
            action_name=tool.name,
            risk=tool.risk.name,
            status="started",
            approval_id=approval_id,
        )
        try:
            result = tool.handler(**args)
        except Exception as exc:
            self.audit.record(
                action_name=tool.name,
                risk=tool.risk.name,
                status="failed",
                approval_id=approval_id,
                details={"error_type": type(exc).__name__},
            )
            raise
        self.audit.record(
            action_name=tool.name,
            risk=tool.risk.name,
            status="completed",
            approval_id=approval_id,
        )
        return result
