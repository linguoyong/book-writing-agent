from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import DB_FILE

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'main',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    meta TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


# ---------------------------------------------------------------- projects


def create_project(name: str, path: str) -> dict[str, Any]:
    project_id = new_id("prj")
    ts = now_iso()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (project_id, name, path, ts, ts),
        )
    return get_project(project_id)  # type: ignore[return-value]


def list_projects() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_project(project_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _row_to_dict(row) if row else None


def touch_project(project_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?", (now_iso(), project_id)
        )


# ---------------------------------------------------------------- sessions


def create_session(project_id: str, title: str = "新会话", kind: str = "main") -> dict[str, Any]:
    session_id = new_id("ses")
    ts = now_iso()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, project_id, title, kind, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, project_id, title, kind, ts, ts),
        )
    result = get_session(session_id)
    assert result is not None
    return result


def list_sessions(project_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE project_id = ? ORDER BY updated_at DESC",
            (project_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_session(session_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return _row_to_dict(row) if row else None


def update_session_title(session_id: str, title: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, now_iso(), session_id),
        )


def delete_session(session_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


# ---------------------------------------------------------------- messages


def add_message(
    session_id: str,
    role: str,
    content: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ts = now_iso()
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO messages (session_id, role, content, meta, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                session_id,
                role,
                content,
                json.dumps(meta, ensure_ascii=False) if meta else None,
                ts,
            ),
        )
        message_id = cursor.lastrowid
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?", (ts, session_id)
        )
    return {
        "id": message_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "meta": meta,
        "created_at": ts,
    }


def list_messages(session_id: str, limit: int = 200) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    result = []
    for row in rows:
        item = _row_to_dict(row)
        item["meta"] = json.loads(item["meta"]) if item["meta"] else None
        result.append(item)
    return result
