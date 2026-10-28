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
    expert_id TEXT,
    domain TEXT,
    permission_mode TEXT,
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

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    message_id UNINDEXED,
    content,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    interrupt_id TEXT,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_approvals_session ON approvals(session_id, status);
"""

# 旧库升级：sessions 增加 expert_id / domain
_MIGRATIONS = {
    "sessions": {
        "expert_id": "ALTER TABLE sessions ADD COLUMN expert_id TEXT",
        "domain": "ALTER TABLE sessions ADD COLUMN domain TEXT",
        "permission_mode": "ALTER TABLE sessions ADD COLUMN permission_mode TEXT",
    }
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        _backfill_fts(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in _MIGRATIONS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, statement in columns.items():
            if column not in existing:
                conn.execute(statement)


def _backfill_fts(conn: sqlite3.Connection) -> None:
    """旧库没有消息索引时补一次，保证「回忆」可用。"""
    from .text import tokenize

    indexed = conn.execute("SELECT COUNT(*) AS n FROM messages_fts").fetchone()["n"]
    total = conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
    if indexed or not total:
        return
    rows = conn.execute("SELECT id, content FROM messages ORDER BY id").fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO messages_fts (message_id, content) VALUES (?, ?)",
            (row["id"], " ".join(tokenize(row["content"]))),
        )


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


def create_session(
    project_id: str,
    title: str = "新会话",
    kind: str = "main",
    expert_id: str | None = None,
    domain: str | None = None,
    permission_mode: str | None = None,
) -> dict[str, Any]:
    session_id = new_id("ses")
    ts = now_iso()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, project_id, title, kind, expert_id, domain, "
            "permission_mode, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                project_id,
                title,
                kind,
                expert_id,
                domain,
                permission_mode,
                ts,
                ts,
            ),
        )
    result = get_session(session_id)
    assert result is not None
    return result


def update_session(session_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"title", "expert_id", "domain", "kind", "permission_mode"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_session(session_id)
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE sessions SET {assignments}, updated_at = ? WHERE id = ?",
            (*updates.values(), now_iso(), session_id),
        )
    return get_session(session_id)


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


def session_titles(session_ids: list[str]) -> dict[str, str]:
    if not session_ids:
        return {}
    placeholders = ",".join("?" for _ in session_ids)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT id, title FROM sessions WHERE id IN ({placeholders})",
            session_ids,
        ).fetchall()
    return {row["id"]: row["title"] for row in rows}


def delete_session(session_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM messages_fts WHERE message_id IN "
            "(SELECT id FROM messages WHERE session_id = ?)",
            (session_id,),
        )
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM approvals WHERE session_id = ?", (session_id,))
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
        from .text import tokenize

        conn.execute(
            "INSERT INTO messages_fts (message_id, content) VALUES (?, ?)",
            (message_id, " ".join(tokenize(content))),
        )
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


def list_messages(session_id: str, limit: int = 200, tail: bool = True) -> list[dict[str, Any]]:
    """按时间正序返回消息。tail=True 表示取「最近 limit 条」，否则取最早 limit 条。"""
    sql = "SELECT * FROM (SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?) ORDER BY id ASC"
    if not tail:
        sql = "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC LIMIT ?"
    with get_conn() as conn:
        rows = conn.execute(sql, (session_id, limit)).fetchall()
    result = []
    for row in rows:
        item = _row_to_dict(row)
        item["meta"] = json.loads(item["meta"]) if item["meta"] else None
        result.append(item)
    return result


def search_messages(query: str, limit: int = 8, project_id: str | None = None) -> list[dict[str, Any]]:
    """跨会话回忆：对历史消息做 FTS 检索。"""
    from .text import fts_query

    match = fts_query(query)
    if not match:
        return []
    sql = (
        "SELECT m.id, m.session_id, m.role, m.content, m.created_at, s.title AS session_title, "
        "messages_fts.rank AS rank "
        "FROM messages_fts JOIN messages m ON m.id = messages_fts.message_id "
        "JOIN sessions s ON s.id = m.session_id "
        "WHERE messages_fts MATCH ?"
    )
    params: list[Any] = [match]
    if project_id:
        sql += " AND s.project_id = ?"
        params.append(project_id)
    sql += " ORDER BY messages_fts.rank LIMIT ?"
    params.append(limit)
    try:
        with get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        {
            "id": row["id"],
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"][:600],
            "created_at": row["created_at"],
            "session_title": row["session_title"],
        }
        for row in rows
    ]


# ---------------------------------------------------------------- approvals


def add_approval(
    session_id: str, interrupt_id: str | None, payload: dict[str, Any]
) -> dict[str, Any]:
    approval_id = new_id("apr")
    ts = now_iso()
    with get_conn() as conn:
        conn.execute(
            "UPDATE approvals SET status = 'expired', decided_at = ? "
            "WHERE session_id = ? AND status = 'pending'",
            (ts, session_id),
        )
        conn.execute(
            "INSERT INTO approvals (id, session_id, interrupt_id, payload, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (
                approval_id,
                session_id,
                interrupt_id,
                json.dumps(payload, ensure_ascii=False),
                ts,
            ),
        )
    result = pending_approval(session_id)
    assert result is not None
    return result


def pending_approval(session_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM approvals WHERE session_id = ? AND status = 'pending' "
            "ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    return _decode_approval(row) if row else None


def resolve_approvals(session_id: str, status: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE approvals SET status = ?, decided_at = ? "
            "WHERE session_id = ? AND status = 'pending'",
            (status, now_iso(), session_id),
        )


def approval_history(session_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM approvals WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [_decode_approval(row) for row in rows]


def _decode_approval(row: sqlite3.Row) -> dict[str, Any]:
    item = _row_to_dict(row)
    item["payload"] = json.loads(item["payload"]) if item["payload"] else {}
    return item
