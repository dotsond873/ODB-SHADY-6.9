import pytest

from shady.memory import MemoryStore


def test_memory_store_persists_memories_and_can_delete(tmp_path):
    path = tmp_path / "shady.sqlite3"
    store = MemoryStore(path)
    saved = store.add_memory("The project is called ODB SHADY 6.9")

    reopened = MemoryStore(path)
    found = reopened.search_memories("ODB SHADY")
    assert found[0].id == saved.id
    assert reopened.delete_memory(saved.id) is True
    assert reopened.list_memories() == []


def test_memory_store_rejects_empty_memory(tmp_path):
    with pytest.raises(ValueError):
        MemoryStore(tmp_path / "db.sqlite3").add_memory("  ")


def test_message_history_is_session_scoped_and_ordered(tmp_path):
    store = MemoryStore(tmp_path / "db.sqlite3")
    store.add_message("one", "user", "Hello")
    store.add_message("one", "assistant", "Hey there")
    store.add_message("two", "user", "Different session")

    history = store.recent_messages("one")
    assert [item.role for item in history] == ["user", "assistant"]
    assert [item.content for item in history] == ["Hello", "Hey there"]
    assert store.clear_session("one") == 2
    assert store.recent_messages("one") == []


def test_invalid_message_role_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        MemoryStore(tmp_path / "db.sqlite3").add_message("one", "system", "Nope")


def test_memory_search_matches_relevant_terms_in_natural_language_query(tmp_path):
    store = MemoryStore(tmp_path / "db.sqlite3")
    store.add_memory("The project codename is SHADY.")
    store.add_memory("The store sells vintage furniture.")

    results = store.search_memories("Tell me about the SHADY project")
    assert [item.content for item in results] == ["The project codename is SHADY."]
