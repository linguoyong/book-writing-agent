from __future__ import annotations

import asyncio
import json
import unittest

from app.agent import runs


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def slow_stream(count: int = 5, delay: float = 0.04):
    for index in range(count):
        await asyncio.sleep(delay)
        yield sse("token", {"text": str(index)})
    yield sse("done", {"chars": count})


class RunRegistryTest(unittest.IsolatedAsyncioTestCase):
    """核心保证：订阅者断开，生成任务照常跑完并把内容留在快照里。"""

    def tearDown(self) -> None:
        runs._runs.clear()

    async def consume(self, state: runs.RunState, stop_after: int = 1) -> list[str]:
        seen: list[str] = []
        async for chunk in runs.tail(state):
            seen.append(chunk)
            if len(seen) >= stop_after:
                break
        return seen

    async def test_reader_disconnect_does_not_stop_run(self) -> None:
        state = runs.start("s1", lambda: slow_stream(5))
        reader = asyncio.create_task(self.consume(state, stop_after=1))

        got = await reader
        self.assertEqual(len(got), 1)

        # 模拟「切走」：订阅者没了，任务继续
        await asyncio.sleep(0.4)
        snapshot = state.snapshot()

        self.assertFalse(snapshot["running"])
        self.assertEqual(snapshot["text"], "01234")
        self.assertFalse(got[0].startswith("event: done"))

    async def test_snapshot_keeps_tool_steps_and_text(self) -> None:
        async def stream():
            yield sse("tool_start", {"name": "read_file", "input": "a.md"})
            await asyncio.sleep(0.01)
            yield sse("tool_end", {"name": "read_file", "output": "内容"})
            yield sse("token", {"text": "写好了"})
            yield sse("done", {})

        state = runs.start("s2", lambda: stream())
        await asyncio.sleep(0.3)

        items = state.snapshot()["items"]
        self.assertEqual(items[0]["type"], "tool")
        self.assertEqual(items[0]["status"], "done")
        self.assertEqual(items[0]["output"], "内容")
        self.assertEqual(state.snapshot()["text"], "写好了")

    async def test_error_is_recorded(self) -> None:
        async def boom():
            yield sse("token", {"text": "开头"})
            raise RuntimeError("炸了")

        state = runs.start("s3", lambda: boom())
        await asyncio.sleep(0.2)

        snapshot = state.snapshot()
        self.assertFalse(snapshot["running"])
        self.assertIn("RuntimeError", snapshot["error"])
        self.assertEqual(snapshot["text"], "开头")

    async def test_running_ids_tracks_live_runs(self) -> None:
        self.assertEqual(runs.running_ids(), set())
        state = runs.start("s4", lambda: slow_stream(3))
        self.assertEqual(runs.running_ids(), {"s4"})
        await asyncio.sleep(0.3)
        self.assertFalse(state.running)
        self.assertEqual(runs.running_ids(), set())

    async def test_tail_after_finish_returns_nothing(self) -> None:
        state = runs.start("s5", lambda: slow_stream(1, delay=0))
        await asyncio.sleep(0.1)

        self.assertEqual(await self.consume(state, stop_after=1), [])


if __name__ == "__main__":
    unittest.main()
