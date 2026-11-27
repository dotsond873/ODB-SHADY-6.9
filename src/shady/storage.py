"""Resolve the local SQLite path shared by every store.

``SHADY_DB_PATH`` applies to chat history, memories, approvals, audit records
and task plans alike, so an operator never ends up with one configured database
and three silent defaults.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DB_PATH = "data/shady.sqlite3"


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    """Return the explicit path, or the location configured in the environment."""
    configured = db_path or os.getenv("SHADY_DB_PATH", DEFAULT_DB_PATH)
    return Path(configured)
