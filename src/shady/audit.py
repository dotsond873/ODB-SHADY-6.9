"""Append-only local audit trail for tool execution events."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class AuditLog:
    """Persist action metadata without recording raw arguments or secrets."""

    def __init__(self, db_path: str | Path = "data/shady.sqlite3") -> None:
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS action_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_name TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    status TEXT NOT NULL,
                    approval_id TEXT,
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.db_path))
        db.row_factory = sqlite3.Row
        return db

    def record(
        self,
        *,
        action_name: str,
        risk: str,
        status: str,
        approval_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        safe_details = json.dumps(details or {}, sort_keys=True)
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO action_audit "
                "(action_name, risk, status, approval_id, details) "
                "VALUES (?, ?, ?, ?, ?)",
                (action_name, risk, status, approval_id, safe_details),
            )
            return int(cursor.lastrowid)

    def recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be at least 1.")
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, action_name, risk, status, approval_id, details, "
                "created_at FROM action_audit ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item["details"])
            events.append(item)
        return events
