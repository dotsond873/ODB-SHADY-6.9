"""One-time, action-specific approval requests."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4


class ApprovalStore:
    """Store pending approvals and consume each approval at most once."""

    def __init__(self, db_path: str | Path = "data/shady.sqlite3") -> None:
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS action_approvals (
                    approval_id TEXT PRIMARY KEY,
                    action_name TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'consumed', 'denied')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    decided_at TEXT
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.db_path))
        db.row_factory = sqlite3.Row
        return db

    def request(self, action_name: str) -> str:
        if not action_name.strip():
            raise ValueError("action_name cannot be empty.")
        approval_id = str(uuid4())
        with self._connect() as db:
            db.execute(
                "INSERT INTO action_approvals(approval_id, action_name, status) "
                "VALUES (?, ?, 'pending')",
                (approval_id, action_name),
            )
        return approval_id

    def approve(self, approval_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE action_approvals SET status='approved', "
                "decided_at=CURRENT_TIMESTAMP "
                "WHERE approval_id=? AND status='pending'",
                (approval_id,),
            )
        return cursor.rowcount == 1

    def deny(self, approval_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE action_approvals SET status='denied', "
                "decided_at=CURRENT_TIMESTAMP "
                "WHERE approval_id=? AND status='pending'",
                (approval_id,),
            )
        return cursor.rowcount == 1

    def consume(self, approval_id: str, action_name: str) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE action_approvals SET status='consumed' "
                "WHERE approval_id=? AND action_name=? AND status='approved'",
                (approval_id, action_name),
            )
        return cursor.rowcount == 1

    def pending(self) -> list[dict[str, str]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT approval_id, action_name, status, created_at "
                "FROM action_approvals WHERE status='pending' ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]
