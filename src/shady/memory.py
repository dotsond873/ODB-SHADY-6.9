"""Local SQLite persistence for user-approved memories and chat history.

The store is intentionally local-first. It does not send data to a cloud service.
Do not save passwords, API keys, payment details, or other secrets as memories.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Memory:
    id: int
    content: str
    created_at: str


@dataclass(frozen=True)
class Message:
    id: int
    session_id: str
    role: str
    content: str
    created_at: str


class MemoryStore:
    """SQLite-backed memory and conversation history."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        configured = db_path or os.getenv("SHADY_DB_PATH", "data/shady.sqlite3")
        self.db_path = Path(configured)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_session_id_id "
                "ON messages(session_id, id)"
            )

    def add_memory(self, content: str) -> Memory:
        value = content.strip()
        if not value:
            raise ValueError("Memory content cannot be empty.")
        with self._connect() as db:
            cursor = db.execute("INSERT INTO memories(content) VALUES (?)", (value,))
            row = db.execute(
                "SELECT id, content, created_at FROM memories WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return Memory(**dict(row))

    def search_memories(self, query: str, *, limit: int = 10) -> list[Memory]:
        terms = [part for part in query.strip().split() if part]
        if not terms:
            return []
        if limit < 1:
            raise ValueError("limit must be at least 1.")
        clauses = " AND ".join("content LIKE ?" for _ in terms)
        params = [f"%{term}%" for term in terms]
        with self._connect() as db:
            rows = db.execute(
                f"SELECT id, content, created_at FROM memories "
                f"WHERE {clauses} ORDER BY id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [Memory(**dict(row)) for row in rows]

    def list_memories(self, *, limit: int = 100) -> list[Memory]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, content, created_at FROM memories "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Memory(**dict(row)) for row in rows]

    def delete_memory(self, memory_id: int) -> bool:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return cursor.rowcount > 0

    def add_message(self, session_id: str, role: str, content: str) -> Message:
        if role not in {"user", "assistant"}:
            raise ValueError("role must be 'user' or 'assistant'.")
        if not session_id.strip() or not content.strip():
            raise ValueError("session_id and content cannot be empty.")
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO messages(session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content.strip()),
            )
            row = db.execute(
                "SELECT id, session_id, role, content, created_at "
                "FROM messages WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return Message(**dict(row))

    def recent_messages(self, session_id: str, *, limit: int = 20) -> list[Message]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, session_id, role, content, created_at FROM messages "
                "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [Message(**dict(row)) for row in reversed(rows)]

    def clear_session(self, session_id: str) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )
        return cursor.rowcount
