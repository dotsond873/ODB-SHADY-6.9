"""Default-deny permission checks for actions with real-world impact."""

from enum import IntEnum


class ActionRisk(IntEnum):
    READ_ONLY = 0
    REVERSIBLE = 1
    CONSEQUENTIAL = 2
    DESTRUCTIVE = 3


class ApprovalRequired(PermissionError):
    """Raised when an action requires explicit user approval."""


class PermissionGate:
    """Require approval for every action beyond read-only access."""

    def authorize(self, risk: ActionRisk, *, approved: bool = False) -> None:
        if risk is not ActionRisk.READ_ONLY and not approved:
            raise ApprovalRequired(
                f"Explicit user approval is required for {risk.name.lower()} actions."
            )
