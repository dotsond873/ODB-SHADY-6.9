import json

import pytest

from shady.permissions import ActionRisk
from shady.planner import TaskPlanner, TaskPlanningError
from shady.providers import ModelRouter
from shady.tools import ToolDefinition, ToolRegistry


class FakeProvider:
    name = "fake"

    def __init__(self, response):
        self.response = response

    def complete(self, *, system_prompt, messages):
        self.last_prompt = system_prompt
        self.last_messages = messages
        return self.response


def make_registry():
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="lookup_order", description="Look up an order",
        risk=ActionRisk.READ_ONLY, handler=lambda order_id: {"status": "ready"},
        required_arguments=frozenset({"order_id"}),
        allowed_arguments=frozenset({"order_id"}),
    ))
    registry.register(ToolDefinition(
        name="send_email", description="Send an email",
        risk=ActionRisk.CONSEQUENTIAL, handler=lambda recipient: "sent",
        required_arguments=frozenset({"recipient"}),
        allowed_arguments=frozenset({"recipient"}),
    ))
    return registry


def test_planner_parses_valid_plan_without_executing_tools():
    response = json.dumps({
        "title": "Check order",
        "steps": [{
            "tool_name": "lookup_order",
            "arguments": {"order_id": "A-17"},
            "description": "Check the order status",
        }],
    })
    provider = FakeProvider(response)
    planner = TaskPlanner(ModelRouter([provider]), make_registry())
    plan = planner.propose("Check order A-17")
    assert plan.title == "Check order"
    assert plan.steps[0].tool_name == "lookup_order"
    assert "send_email" in provider.last_messages[0]["content"]


def test_planner_rejects_unknown_tool():
    response = json.dumps({
        "title": "Bad plan",
        "steps": [{"tool_name": "run_shell", "arguments": {},
                   "description": "run a command"}],
    })
    planner = TaskPlanner(ModelRouter([FakeProvider(response)]), make_registry())
    with pytest.raises(TaskPlanningError, match="unregistered"):
        planner.propose("Do something")


def test_planner_rejects_missing_or_extra_arguments():
    response = json.dumps({
        "title": "Bad plan",
        "steps": [{"tool_name": "lookup_order",
                   "arguments": {"wrong": "x"},
                   "description": "look up"}],
    })
    planner = TaskPlanner(ModelRouter([FakeProvider(response)]), make_registry())
    with pytest.raises(TaskPlanningError, match="arguments"):
        planner.propose("Check")


def test_planner_rejects_extra_fields_and_non_json():
    planner = TaskPlanner(ModelRouter([FakeProvider("{}")]), make_registry())
    with pytest.raises(TaskPlanningError):
        planner.propose("Check")
    with pytest.raises(ValueError):
        planner.propose("  ")


def test_planner_never_executes_even_consequential_steps():
    calls = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="send_email", description="Send", risk=ActionRisk.CONSEQUENTIAL,
        handler=lambda recipient: calls.append(recipient),
        required_arguments=frozenset({"recipient"}),
        allowed_arguments=frozenset({"recipient"}),
    ))
    response = json.dumps({
        "title": "Email",
        "steps": [{"tool_name": "send_email", "arguments": {"recipient": "x"},
                   "description": "Send only after approval"}],
    })
    plan = TaskPlanner(ModelRouter([FakeProvider(response)]), registry).propose("Email x")
    assert plan.steps[0].tool_name == "send_email"
    assert calls == []
