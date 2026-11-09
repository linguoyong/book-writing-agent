"""对话线程标识的唯一来源。

thread_id 决定 checkpoint 落在哪条通道上。写稿、审稿、侧问各用各的命名空间，
否则消息通道会串。所有生成逻辑都从这里取，不要在业务代码里手写 f-string。
"""

from __future__ import annotations

import re
import time
from typing import Any

REVIEW_NS = "review"
_SAFE = re.compile(r"[^\w\u4e00-\u9fff-]+")


def session_thread(session: dict[str, Any] | None, session_id: str = "") -> str:
    """会话主线程：优先用已落库的 thread_id（重新生成时会换一条）。"""
    data = session or {}
    return str(data.get("thread_id") or data.get("id") or session_id)


def fork_thread(session_id: str) -> str:
    """重新生成：换一条 checkpoint 通道，旧历史留在原通道里。"""
    return f"{session_id}-r{int(time.time() * 1000)}"


def review_thread(session_id: str, target: str, round_no: int = 1) -> str:
    """审稿的命名空间。

    审稿本身是一次独立模型调用，不进主图；这个标识留给以后要做「审稿子图」
    或「多轮修订会话」时用，提前把规则定下来，避免届时不兼容。
    """
    safe = _SAFE.sub("-", target or "chapter").strip("-") or "chapter"
    return f"{session_id}:{REVIEW_NS}:{safe}:{max(1, int(round_no))}"
