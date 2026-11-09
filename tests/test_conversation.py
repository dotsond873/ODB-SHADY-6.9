from shady.conversation import ConversationService
from shady.memory import MemoryStore
from shady.providers import ModelRouter


class EchoProvider:
    name = "echo"

    def complete(self, *, system_prompt, messages):
        assert "ODB SHADY 6.9" in system_prompt
        return "Shady received: " + messages[-1]["content"]


def test_conversation_saves_exchange_and_reuses_history(tmp_path):
    store = MemoryStore(tmp_path / "shady.sqlite3")
    service = ConversationService(
        ModelRouter([EchoProvider()]),
        store,
        session_id="test-session",
    )

    answer = service.reply("Hello there")
    assert answer == "Shady received: Hello there"

    history = store.recent_messages("test-session")
    assert [message.role for message in history] == ["user", "assistant"]
    assert history[0].content == "Hello there"
    assert history[1].content == answer


def test_relevant_saved_memory_is_included_in_prompt(tmp_path):
    store = MemoryStore(tmp_path / "shady.sqlite3")
    store.add_memory("The project codename is SHADY.")

    class InspectProvider:
        name = "inspect"

        def complete(self, *, system_prompt, messages):
            assert "The project codename is SHADY." in system_prompt
            return "Memory found."

    service = ConversationService(
        ModelRouter([InspectProvider()]),
        store,
        session_id="memory-session",
    )
    assert service.reply("Tell me about SHADY") == "Memory found."


def test_failed_provider_does_not_save_half_exchange(tmp_path):
    store = MemoryStore(tmp_path / "shady.sqlite3")

    class BrokenProvider:
        name = "broken"

        def complete(self, *, system_prompt, messages):
            raise RuntimeError("offline")

    service = ConversationService(
        ModelRouter([BrokenProvider()]),
        store,
        session_id="failed-session",
    )
    try:
        service.reply("This should not be stored")
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected provider failure")

    assert store.recent_messages("failed-session") == []
