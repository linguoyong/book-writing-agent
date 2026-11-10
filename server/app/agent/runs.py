"""会话级运行登记：把 Agent 执行从 HTTP 请求里解耦。

原来 SSE 生成器直接跑在请求里，客户端一断开（切到别的会话、切空间），
uvicorn 取消生成器 → 这一轮就断了，已生成的内容也不会落库。

现在 `POST /chat` 只做两件事：
1. `start()` 一个后台任务，任务里跑原来的生成器（内容照常落库）；
2. 用 `tail()` 订阅这个任务的事件，作为响应体返回。

断开响应只是取消订阅，任务继续跑完。切回来用 `GET /sessions/{id}/run`
拿快照（已生成的文本 + 工具步骤 + 是否还在跑），继续看进展。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

# 跑完之后快照留一会儿：用户切回来还能看到「刚才那轮」的痕迹
KEEP_FINISHED_SECONDS = 600
# 重放缓冲上限，防止超长任务把内存吃穿
MAX_ITEMS = 4000

_runs: dict[str, RunState] = {}


@dataclass
class RunState:
    session_id: str
    running: bool = True
    items: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    task: asyncio.Task[None] | None = None
    subscribers: set[asyncio.Queue[str | None]] = field(default_factory=set)
    after_message_id: int = 0

    @property
    def text(self) -> str:
        parts = [item["content"] for item in self.items if item.get("type") == "text"]
        return "".join(parts)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "running": self.running,
            "items": self.items,
            "text": self.text,
            "error": self.error,
            "started_at": self.started_at,
            "elapsed_ms": int(((self.finished_at or time.time()) - self.started_at) * 1000),
            "after_message_id": self.after_message_id,
        }

    def _append_text(self, text: str) -> None:
        if not text:
            return
        last = self.items[-1] if self.items else None
        if last is not None and last.get("type") == "text":
            last["content"] = str(last["content"]) + text
            return
        if len(self.items) < MAX_ITEMS:
            self.items.append({"type": "text", "content": text})

    def _push_item(self, item: dict[str, Any]) -> None:
        if len(self.items) < MAX_ITEMS:
            self.items.append(item)


def get_run(session_id: str) -> RunState | None:
    return _runs.get(session_id)


def is_running(session_id: str) -> bool:
    state = _runs.get(session_id)
    return bool(state and state.running)


def cancel(session_id: str) -> bool:
    """用户点「停止生成」：取消后台任务，已生成内容由生成器的 finally 落库。"""
    state = _runs.get(session_id)
    if state is None or not state.running or state.task is None:
        return False
    state.task.cancel()
    return True


def running_ids() -> set[str]:
    return {session_id for session_id, state in _runs.items() if state.running}


def start(
    session_id: str, factory: Callable[[], AsyncIterator[str]], *, after_message_id: int = 0
) -> RunState:
    """启动（或接管）一轮生成。调用方负责先确认没有在跑的轮次。"""
    state = RunState(session_id=session_id, after_message_id=after_message_id)
    previous = _runs.get(session_id)
    if previous and previous.running and previous.task:
        previous.task.cancel()
    # 先建任务再登记：在没有事件循环的线程里调用时 create_task 会抛
    # RuntimeError，如果先登记就会留下一个永远 running=True 的僵尸条目，
    # 之后所有请求都只会拿到 409。
    state.task = asyncio.create_task(_drive(state, factory))
    _runs[session_id] = state
    return state


async def _drive(state: RunState, factory: Callable[[], AsyncIterator[str]]) -> None:
    try:
        async for chunk in factory():
            _record(state, chunk)
            _broadcast(state, chunk)
    except asyncio.CancelledError:
        state.error = state.error or "本轮已中断"
        raise
    except Exception as exc:  # noqa: BLE001 - 任务里必须兜住，否则静默死掉
        state.error = f"{type(exc).__name__}: {exc}"
        _broadcast(state, _sse("error", {"message": state.error}))
    finally:
        state.running = False
        state.finished_at = time.time()
        _broadcast(state, None)
        state.subscribers.clear()
        # 留一段时间给「切回来」的场景，之后回收
        loop = asyncio.get_running_loop()
        loop.call_later(KEEP_FINISHED_SECONDS, _forget, state.session_id, state)


def _forget(session_id: str, state: RunState) -> None:
    if _runs.get(session_id) is state:
        _runs.pop(session_id, None)


def _broadcast(state: RunState, chunk: str | None) -> None:
    for queue in list(state.subscribers):
        queue.put_nowait(chunk)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _record(state: RunState, chunk: str) -> None:
    """从 SSE 文本里抽出 token 与工具调用，攒成可回放的快照。"""
    event = ""
    payload: dict[str, Any] = {}
    for line in chunk.splitlines():
        if line.startswith("event: "):
            event = line[7:].strip()
        elif line.startswith("data: "):
            try:
                payload = json.loads(line[6:])
            except json.JSONDecodeError:
                payload = {}
    if event == "token":
        state._append_text(str(payload.get("text") or ""))
    elif event == "tool_start":
        state._push_item(
            {
                "type": "tool",
                "name": str(payload.get("name") or "tool"),
                "input": str(payload.get("input") or ""),
                "output": "",
                "status": "running",
            }
        )
    elif event == "tool_end":
        name = str(payload.get("name") or "tool")
        for item in reversed(state.items):
            if (
                item.get("type") == "tool"
                and item.get("name") == name
                and item.get("status") == "running"
            ):
                item["output"] = str(payload.get("output") or "")
                item["status"] = "done"
                break
        else:
            state._push_item(
                {
                    "type": "tool",
                    "name": name,
                    "input": "",
                    "output": str(payload.get("output") or ""),
                    "status": "done",
                }
            )
    elif event == "error":
        state.error = str(payload.get("message") or "未知错误")
    elif event == "retry":
        remaining = max(0, int(payload.get("removed_chars") or 0))
        for item in reversed(state.items):
            if remaining and item.get("type") == "text":
                text = item["content"]
                removed = min(remaining, len(text))
                item["content"] = text[: len(text) - removed]
                remaining -= removed
        state.items[:] = [
            item for item in state.items if item.get("type") != "text" or item["content"]
        ]
        state._push_item({"type": "notice", "content": str(payload.get("message") or "正在重试")})


async def tail(state: RunState) -> AsyncIterator[str]:
    """订阅一个运行中的任务：只转发之后产生的事件。"""
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    state.subscribers.add(queue)
    try:
        if not state.running:
            return
        while True:
            item = await queue.get()
            if item is None:
                return
            yield item
    finally:
        state.subscribers.discard(queue)
