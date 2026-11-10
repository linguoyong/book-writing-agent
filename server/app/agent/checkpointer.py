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
    """删除会话及重新生成留下的所有 checkpoint 通道。"""
    if _saver is not None and _conn is not None:
        prefix = session_id + "-r"
        async with _conn.execute(
            "SELECT DISTINCT thread_id FROM checkpoints "
            "WHERE thread_id = ? OR substr(thread_id, 1, ?) = ?",
            (session_id, len(prefix), prefix),
        ) as cursor:
            thread_ids = [row[0] for row in await cursor.fetchall()]
        for thread_id in {session_id, *thread_ids}:
            await _saver.adelete_thread(thread_id)
