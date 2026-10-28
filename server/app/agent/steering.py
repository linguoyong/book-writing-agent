from __future__ import annotations


from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import HumanMessage

_INBOX: dict[str, list[str]] = {}
_RUNNING: set[str] = set()


def begin(session_id: str) -> None:
    _RUNNING.add(session_id)


def end(session_id: str) -> None:
    _RUNNING.discard(session_id)


def is_running(session_id: str) -> bool:
    return session_id in _RUNNING


def enqueue(session_id: str, text: str) -> int:
    """把一条引导消息放进队列，返回当前排队数量。"""
    queue = _INBOX.setdefault(session_id, [])
    queue.append(text.strip())
    return len(queue)


def drain(session_id: str) -> list[str]:
    return _INBOX.pop(session_id, [])


def pending_count(session_id: str) -> int:
    return len(_INBOX.get(session_id, []))


class SteeringMiddleware(AgentMiddleware):
    """在每次模型调用前，把用户执行中插入的引导消息并进对话。

    这样不打断当前 run，模型在下一步就能看到新指示，相当于「中途换方向」。
    """

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self.session_id = session_id

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        texts = drain(self.session_id)
        if not texts:
            return None
        bullets = "\n".join(f"- {text}" for text in texts)
        content = (
            "<steering>\n"
            "用户在你执行过程中补充了下面的指示。请在不推翻已完成工作、不重复已做步骤的前提下，"
            "从下一步开始按新指示调整方向：\n"
            f"{bullets}\n"
            "</steering>"
        )
        return {"messages": [HumanMessage(content=content)]}
