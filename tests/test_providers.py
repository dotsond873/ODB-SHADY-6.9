import pytest

from shady.providers import ModelRouter


class StubProvider:
    def __init__(self, name, result=None, error=None):
        self.name = name
        self.result = result
        self.error = error
        self.calls = 0

    def complete(self, *, system_prompt, messages):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def test_router_uses_first_healthy_provider():
    first = StubProvider("first", error=RuntimeError("offline"))
    second = StubProvider("second", result="Shady is online")
    router = ModelRouter([first, second])

    assert router.complete(system_prompt="system", messages=[]) == "Shady is online"
    assert first.calls == 1
    assert second.calls == 1


def test_router_can_prefer_a_named_provider():
    first = StubProvider("first", result="one")
    second = StubProvider("second", result="two")
    router = ModelRouter([first, second])

    assert router.complete(
        system_prompt="system", messages=[], preferred="second"
    ) == "two"
    assert second.calls == 1
    assert first.calls == 0


def test_router_rejects_unknown_preferred_provider():
    router = ModelRouter([StubProvider("first", result="one")])
    with pytest.raises(ValueError, match="Unknown model"):
        router.complete(system_prompt="system", messages=[], preferred="missing")


def test_router_reports_all_provider_failures():
    router = ModelRouter([
        StubProvider("alpha", error=RuntimeError("down")),
        StubProvider("beta", error=TimeoutError("slow")),
    ])
    with pytest.raises(RuntimeError, match="All configured"):
        router.complete(system_prompt="system", messages=[])
