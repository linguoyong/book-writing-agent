from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool

from app.agent.runner import _error_text, _persist_assistant, _run_events
from app.usage import UsageMeter


class StreamVisibilityTest(unittest.TestCase):
    def consume(self, agent):
        buffer, calls, paths, events = [], [], set(), []
        meter = UsageMeter()

        async def run():
            async for event in _run_events(agent, {}, {}, buffer, calls, paths, meter):
                events.append(event)

        asyncio.run(run())
        return buffer, calls, paths, events, meter

    def test_real_tool_model_stream_is_hidden_but_main_model_is_visible(self):
        @tool
        async def chapter_review() -> str:
            """Review a chapter privately."""
            model = FakeListChatModel(responses=['{"dimensions":{"structure":5}}'])
            async for _ in model.astream("review"):
                pass
            return "review complete"

        async def chat(_):
            await chapter_review.ainvoke({})
            model = FakeListChatModel(responses=["final answer"])
            async for chunk in model.astream("answer"):
                yield chunk

        buffer, calls, _, events, _ = self.consume(RunnableLambda(chat))
        self.assertEqual("".join(buffer), "final answer")
        self.assertEqual([call["name"] for call in calls], ["chapter_review"])
        self.assertEqual(calls[0]["status"], "done")
        self.assertNotIn("dimensions", "".join(events))

    def test_nested_tools_and_late_internal_tokens_are_hidden_and_writes_tracked(self):
        def event(kind, run, parents=(), name="model", **data):
            return {
                "event": kind,
                "run_id": run,
                "parent_ids": list(parents),
                "name": name,
                "data": data,
            }

        class Agent:
            async def astream_events(self, *args, **kwargs):
                yield event("on_tool_start", "outer", name="task", input={})
                yield event(
                    "on_tool_start",
                    "write",
                    ["outer"],
                    name="write_file",
                    input={"file_path": "/manuscript/ch-001.md"},
                )
                yield event(
                    "on_chat_model_stream",
                    "inner",
                    ["outer", "write"],
                    chunk=SimpleNamespace(content="secret"),
                )
                yield event("on_tool_end", "write", ["outer"], name="write_file", output="ok")
                yield event("on_tool_end", "outer", name="task", output="done")
                yield event(
                    "on_chat_model_stream",
                    "late",
                    ["outer"],
                    chunk=SimpleNamespace(content="late secret"),
                )
                tagged = event(
                    "on_chat_model_stream", "tagged", chunk=SimpleNamespace(content="tagged secret")
                )
                yield {**tagged, "tags": ["book:internal"]}
                summary = event(
                    "on_chat_model_stream",
                    "summary",
                    chunk=SimpleNamespace(content="summary secret"),
                )
                yield {**summary, "metadata": {"lc_source": "summarization"}}
                yield event(
                    "on_chat_model_stream", "main", chunk=SimpleNamespace(content="visible")
                )

        buffer, calls, paths, events, _ = self.consume(Agent())
        self.assertEqual(buffer, ["visible"])
        self.assertEqual([call["name"] for call in calls], ["task"])
        self.assertEqual(paths, {"manuscript/ch-001.md"})
        self.assertNotIn("secret", "".join(events))

    def test_separately_metered_model_is_not_counted_twice(self):
        message = SimpleNamespace(
            usage_metadata={"input_tokens": 10, "output_tokens": 5},
            response_metadata={"model_name": "fake"},
        )

        class Agent:
            async def astream_events(self, *args, **kwargs):
                for tags in (["book:internal", "book:metered"], ["book:internal"], []):
                    yield {"event": "on_chat_model_end", "tags": tags, "data": {"output": message}}

        *_, meter = self.consume(Agent())
        self.assertEqual(meter.as_dict()["total"], 30)

    def test_history_preserves_process_order_and_stores_only_final_answer_as_content(self):
        calls = [
            {
                "name": "chapter_review",
                "input": "{}",
                "output": "done",
                "offset": 7,
                "status": "done",
            }
        ]
        with patch("app.agent.runner.db.add_message") as add:
            _persist_assistant("session", ["process", "final"], calls, awaiting=False)
        self.assertEqual(add.call_args.args, ("session", "assistant", "final"))
        trace = add.call_args.kwargs["meta"]["timeline"]
        self.assertEqual([item["type"] for item in trace], ["text", "tool", "text"])
        self.assertEqual(trace[0]["content"], "process")
        self.assertEqual(trace[2]["content"], "final")
        json.dumps(trace)

    def test_tools_only_turn_is_persisted_and_generic_error_does_not_recurse(self):
        with patch("app.agent.runner.db.add_message") as add:
            _persist_assistant(
                "session",
                [],
                [{"name": "read_file", "input": "a.md", "offset": 0}],
                awaiting=False,
                interrupted=True,
            )
        self.assertTrue(add.called)
        self.assertEqual(add.call_args.args[2], "")
        self.assertEqual(_error_text(RuntimeError("boom")), "RuntimeError: boom")
