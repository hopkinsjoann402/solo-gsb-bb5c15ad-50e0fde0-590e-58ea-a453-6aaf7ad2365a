"""SQLite persistence for validated measures.

The database schema is created on application startup, so a single
``docker compose up`` performs dependency installation, database
initialisation and service start.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

# Configurable via environment; /data is the Docker volume mount point.
DB_PATH = os.environ.get("DATABASE_PATH", "./data/measures.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS measures (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    target_duration TEXT NOT NULL,
    payload         TEXT NOT NULL,   -- JSON: voices with assigned event ids
    grid            TEXT NOT NULL,   -- JSON: half-open segments
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""


def _connect() -> sqlite3.Connection:
    path = Path(DB_PATH)
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    """Create the schema if it does not exist yet (idempotent)."""
    with _connect() as connection:
        connection.executescript(_SCHEMA)


def insert_measure(measure: dict[str, Any]) -> int:
    """Persist a validated measure and return its new id."""
    payload = {
        "target_duration": measure["target_duration"],
        "voices": measure["voices"],
    }
    grid = {"segments": measure["segments"]}
    with _connect() as connection:
        cursor = connection.execute(
            "INSERT INTO measures (target_duration, payload, grid) VALUES (?, ?, ?)",
            (
                measure["target_duration"],
                json.dumps(payload, ensure_ascii=False),
                json.dumps(grid, ensure_ascii=False),
            ),
        )
        return int(cursor.lastrowid)


def get_measure(measure_id: int) -> dict[str, Any] | None:
    """Fetch a stored measure (voices + grid) by id, or ``None``."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, target_duration, payload, grid, created_at "
            "FROM measures WHERE id = ?",
            (measure_id,),
        ).fetchone()
    if row is None:
        return None
    payload = json.loads(row["payload"])
    grid = json.loads(row["grid"])
    return {
        "id": row["id"],
        "target_duration": row["target_duration"],
        "voices": payload["voices"],
        "segments": grid["segments"],
        "created_at": row["created_at"],
    }
