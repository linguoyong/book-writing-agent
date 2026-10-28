from __future__ import annotations

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ..config import DB_FILE

_saver: AsyncSqliteSaver | None = None
_conn: aiosqlite.Connection | None = None


async def init_checkpointer() -> None:
    """会话状态持久化：与业务表同库，WAL 模式下并发读写安全。"""
    global _saver, _conn
    if _saver is not None:
        return
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    _conn = await aiosqlite.connect(DB_FILE)
    _saver = AsyncSqliteSaver(_conn)
    await _saver.setup()


def get_checkpointer() -> AsyncSqliteSaver | None:
    return _saver


async def close_checkpointer() -> None:
    global _saver, _conn
    if _conn is not None:
        await _conn.close()
    _saver = None
    _conn = None


async def drop_thread(session_id: str) -> None:
    if _saver is not None:
        await _saver.adelete_thread(session_id)
