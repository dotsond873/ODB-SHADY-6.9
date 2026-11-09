import pytest

from shady.engine import ShadyEngine
from shady.identity import SHADY_IDENTITY
from shady.permissions import ActionRisk, ApprovalRequired, PermissionGate


def test_identity_has_name_and_guardrails():
    assert SHADY_IDENTITY["name"] == "ODB SHADY 6.9"
    assert any("truth" in item.lower() for item in SHADY_IDENTITY["principles"])


def test_engine_reports_missing_provider_honestly():
    with pytest.raises(RuntimeError, match="No model provider"):
        ShadyEngine().ask("Hello, Shady")


def test_engine_calls_configured_provider():
    def provider(**kwargs):
        return f"Received: {kwargs['message']}"

    assert ShadyEngine(provider).ask("Hello") == "Received: Hello"


def test_read_only_does_not_require_approval():
    PermissionGate().authorize(ActionRisk.READ_ONLY)


@pytest.mark.parametrize("risk", [ActionRisk.REVERSIBLE, ActionRisk.CONSEQUENTIAL, ActionRisk.DESTRUCTIVE])
def test_other_actions_require_approval(risk):
    with pytest.raises(ApprovalRequired):
        PermissionGate().authorize(risk)


def test_approved_action_is_allowed():
    PermissionGate().authorize(ActionRisk.DESTRUCTIVE, approved=True)
