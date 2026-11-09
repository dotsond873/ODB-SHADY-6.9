"""Persistent, resumable task plans for Shady.

Task arguments are stored locally as JSON. Never put credentials, passwords,
payment data, or other secrets in task arguments.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from uuid import uuid4
from typing import Any, Mapping, Sequence


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class PlannedStep:
    tool_name: str
    arguments: Mapping[str, Any]
    description: str = ""


@dataclass(frozen=True)
class TaskStep:
    id: int
    task_id: str
    position: int
    tool_name: str
    arguments: dict[str, Any]
    description: str
    status: StepStatus
    approval_id: str | None
    result_summary: str | None
    error_type: str | None


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    status: TaskStatus
    created_at: str
    updated_at: str
    steps: tuple[TaskStep, ...]


class TaskStore:
    """SQLite-backed task/step state with explicit state transitions."""

    def __init__(self, db_path: str | Path = "data/shady.sqlite3") -> None:
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS task_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                approval_id TEXT,
                result_summary TEXT,
                error_type TEXT,
                UNIQUE(task_id, position)
            )""")
            db.execute("PRAGMA foreign_keys=ON")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.db_path))
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def create_task(self, title: str, steps: Sequence[PlannedStep]) -> Task:
        title = title.strip()
        if not title:
            raise ValueError("Task title cannot be empty.")
        if not steps:
            raise ValueError("A task must contain at least one step.")
        task_id = str(uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO tasks(task_id, title, status) VALUES (?, ?, ?)",
                       (task_id, title, TaskStatus.QUEUED.value))
            for position, step in enumerate(steps):
                if not step.tool_name.strip():
                    raise ValueError("Step tool_name cannot be empty.")
                try:
                    args_json = json.dumps(dict(step.arguments), allow_nan=False)
                except (TypeError, ValueError) as exc:
                    raise ValueError("Step arguments must be JSON-serializable.") from exc
                db.execute("""INSERT INTO task_steps
                    (task_id, position, tool_name, arguments_json, description, status)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (task_id, position, step.tool_name, args_json,
                     step.description, StepStatus.PENDING.value))
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> Task:
        with self._connect() as db:
            task = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if task is None:
                raise KeyError(f"Unknown task: {task_id}")
            rows = db.execute("SELECT * FROM task_steps WHERE task_id=? ORDER BY position",
                              (task_id,)).fetchall()
        steps = tuple(TaskStep(
            id=row["id"], task_id=row["task_id"], position=row["position"],
            tool_name=row["tool_name"], arguments=json.loads(row["arguments_json"]),
            description=row["description"], status=StepStatus(row["status"]),
            approval_id=row["approval_id"], result_summary=row["result_summary"],
            error_type=row["error_type"],
        ) for row in rows)
        return Task(task_id, task["title"], TaskStatus(task["status"]),
                    task["created_at"], task["updated_at"], steps)

    def list_tasks(self, *, limit: int = 50) -> list[Task]:
        if limit < 1:
            raise ValueError("limit must be at least 1.")
        with self._connect() as db:
            ids = db.execute("SELECT task_id FROM tasks ORDER BY created_at DESC LIMIT ?",
                             (limit,)).fetchall()
        return [self.get_task(row["task_id"]) for row in ids]

    def set_step(self, step_id: int, status: StepStatus, *,
                 approval_id: str | None = None, result_summary: str | None = None,
                 error_type: str | None = None) -> None:
        with self._connect() as db:
            row = db.execute("SELECT task_id FROM task_steps WHERE id=?", (step_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown task step: {step_id}")
            db.execute("""UPDATE task_steps SET status=?, approval_id=COALESCE(?, approval_id),
                result_summary=?, error_type=? WHERE id=?""",
                (status.value, approval_id, result_summary, error_type, step_id))
            self._refresh_task_status(db, row["task_id"])

    def cancel_task(self, task_id: str) -> Task:
        with self._connect() as db:
            row = db.execute("SELECT status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown task: {task_id}")
            if TaskStatus(row["status"]) in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
                raise ValueError("Completed or cancelled tasks cannot be cancelled again.")
            db.execute("UPDATE task_steps SET status=? WHERE task_id=? AND status IN (?, ?)",
                       (StepStatus.CANCELLED.value, task_id,
                        StepStatus.PENDING.value, StepStatus.WAITING_APPROVAL.value))
            db.execute("UPDATE tasks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE task_id=?",
                       (TaskStatus.CANCELLED.value, task_id))
        return self.get_task(task_id)

    @staticmethod
    def _refresh_task_status(db: sqlite3.Connection, task_id: str) -> None:
        rows = db.execute("SELECT status FROM task_steps WHERE task_id=? ORDER BY position",
                          (task_id,)).fetchall()
        states = [StepStatus(row["status"]) for row in rows]
        if all(state is StepStatus.COMPLETED for state in states):
            status = TaskStatus.COMPLETED
        elif any(state is StepStatus.WAITING_APPROVAL for state in states):
            status = TaskStatus.WAITING_APPROVAL
        elif any(state is StepStatus.FAILED for state in states):
            status = TaskStatus.FAILED
        else:
            status = TaskStatus.RUNNING
        db.execute("UPDATE tasks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE task_id=?",
                   (status.value, task_id))
