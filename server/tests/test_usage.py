from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app import db, usage
from app.config import Settings


class FakeMessage:
    """够用的 AIMessage 替身：只要有 usage_metadata / response_metadata。"""

    def __init__(
        self,
        usage: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
        content: str = "ok",
    ) -> None:
        self.usage_metadata = usage or {}
        self.response_metadata = meta or {}
        self.content = content


class UsageTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        self._old_db = db.DB_FILE
        db.DB_FILE = self.tmp / "app.db"
        self.addCleanup(setattr, db, "DB_FILE", self._old_db)
        db.init_db()

        # 配置落到内存里，避免写用户真实的 config.json
        self.settings = Settings()
        self._old_load = usage.load_settings
        self._old_save = usage.save_settings
        usage.load_settings = lambda: self.settings
        usage.save_settings = lambda settings: setattr(self, "settings", settings)
        self.addCleanup(setattr, usage, "load_settings", self._old_load)
        self.addCleanup(setattr, usage, "save_settings", self._old_save)

        project = db.create_project("测试书", str(self.tmp / "book"))
        self.project_id = project["id"]
        self.session = db.create_session(self.project_id, title="第一章讨论")


class ParseMessageTest(unittest.TestCase):
    def test_usage_metadata(self) -> None:
        parsed = usage.parse_message(
            FakeMessage(
                usage={
                    "input_tokens": 1200,
                    "output_tokens": 340,
                    "input_token_details": {"cache_read": 800},
                },
                meta={"model_name": "deepseek-chat"},
            )
        )
        self.assertEqual(parsed["input"], 1200)
        self.assertEqual(parsed["output"], 340)
        self.assertEqual(parsed["cache_read"], 800)
        self.assertEqual(parsed["model"], "deepseek-chat")
        self.assertTrue(parsed["reported"])

    def test_fallback_to_response_metadata(self) -> None:
        parsed = usage.parse_message(
            FakeMessage(meta={"token_usage": {"prompt_tokens": 90, "completion_tokens": 30}})
        )
        self.assertEqual(parsed["input"], 90)
        self.assertEqual(parsed["output"], 30)
        self.assertTrue(parsed["reported"])

    def test_missing_usage_is_unreported(self) -> None:
        parsed = usage.parse_message(FakeMessage())
        self.assertEqual(parsed["input"], 0)
        self.assertEqual(parsed["output"], 0)
        self.assertFalse(parsed["reported"])


class MeterTest(UsageTestBase):
    def test_accumulates(self) -> None:
        meter = usage.UsageMeter()
        meter.add(FakeMessage(usage={"input_tokens": 100, "output_tokens": 40}))
        meter.add(FakeMessage(usage={"input_tokens": 200, "output_tokens": 60}))
        snapshot = meter.as_dict()
        self.assertEqual(snapshot["input"], 300)
        self.assertEqual(snapshot["output"], 100)
        self.assertEqual(snapshot["total"], 400)
        self.assertEqual(snapshot["calls"], 2)

    def test_flush_writes_once(self) -> None:
        meter = usage.UsageMeter()
        meter.add(FakeMessage(usage={"input_tokens": 10, "output_tokens": 5}))
        first = meter.flush(project_id=self.project_id, session_id=self.session["id"])
        self.assertIsNotNone(first)
        self.assertIsNone(meter.flush(project_id=self.project_id))
        summary = usage.summary(self.project_id, 7)
        self.assertEqual(summary["totals"]["total"], 15)
        self.assertEqual(summary["recorded"], 1)

    def test_unreported_call_still_counted(self) -> None:
        meter = usage.UsageMeter()
        meter.add(FakeMessage())
        self.assertEqual(meter.as_dict()["calls"], 1)
        self.assertIsNotNone(meter.flush(project_id=self.project_id))

    def test_no_calls_no_row(self) -> None:
        meter = usage.UsageMeter()
        self.assertIsNone(meter.flush(project_id=self.project_id))
        self.assertEqual(usage.summary(self.project_id)["recorded"], 0)


class RecordTest(UsageTestBase):
    def test_empty_record_skipped(self) -> None:
        self.assertIsNone(usage.record(project_id=self.project_id))
        self.assertIsNone(usage.record(project_id=""))
        self.assertEqual(usage.summary(self.project_id)["recorded"], 0)

    def test_negative_values_clamped(self) -> None:
        usage.record(project_id=self.project_id, input_tokens=-10, output_tokens=-5, calls=1)
        totals = usage.summary(self.project_id, 7)["totals"]
        self.assertEqual(totals["input"], 0)
        self.assertEqual(totals["output"], 0)


class SummaryTest(UsageTestBase):
    def seed(self) -> None:
        usage.record(
            project_id=self.project_id,
            session_id=self.session["id"],
            model="deepseek-chat",
            input_tokens=1000,
            output_tokens=200,
            calls=3,
        )
        usage.record(
            project_id=self.project_id,
            session_id=self.session["id"],
            model="deepseek-chat",
            input_tokens=500,
            output_tokens=100,
            cache_read=400,
            calls=1,
        )
        usage.record(
            project_id=self.project_id,
            kind="extract",
            model="bge-rerank",
            input_tokens=4000,
            output_tokens=800,
            calls=1,
        )

    def test_groups(self) -> None:
        self.seed()
        result = usage.summary(self.project_id, 7)
        self.assertEqual(result["totals"]["total"], 6600)
        self.assertEqual(result["totals"]["calls"], 5)
        self.assertEqual(result["today"]["total"], 6600)
        self.assertEqual(len(result["series"]), 7)
        self.assertEqual(result["series"][-1]["total"], 6600)
        models = {row["model"]: row["total"] for row in result["by_model"]}
        self.assertEqual(models["deepseek-chat"], 1800)
        self.assertEqual(models["bge-rerank"], 4800)
        kinds = {row["kind"]: row["total"] for row in result["by_kind"]}
        self.assertEqual(kinds["chat"], 1800)
        self.assertEqual(kinds["extract"], 4800)
        self.assertEqual(result["by_session"][0]["title"], "第一章讨论")
        self.assertEqual(result["by_session"][0]["turns"], 2)

    def test_cost_without_pricing(self) -> None:
        self.seed()
        result = usage.summary(self.project_id, 7)
        self.assertEqual(result["cost"]["total"], 0.0)
        self.assertFalse(result["cost"]["has_pricing"])

    def test_cost_with_pricing(self) -> None:
        self.seed()
        usage.set_pricing({"deepseek-chat": {"input": 2.0, "output": 8.0}})
        result = usage.summary(self.project_id, 7)
        # 1500 输入 × 2 + 300 输出 × 8 = 0.003 + 0.0024
        self.assertAlmostEqual(result["cost"]["total"], 0.0054, places=4)
        self.assertTrue(result["cost"]["has_pricing"])
        rows = {row["model"]: row["cost"] for row in result["by_model"]}
        self.assertAlmostEqual(rows["deepseek-chat"], 0.0054, places=4)
        self.assertEqual(rows["bge-rerank"], 0.0)

    def test_window_excludes_old_rows(self) -> None:
        usage.record(
            project_id=self.project_id,
            model="deepseek-chat",
            input_tokens=999,
            output_tokens=1,
            calls=1,
        )
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO usage_log (project_id, session_id, kind, model, input_tokens, "
                "output_tokens, cache_read, calls, elapsed_ms, created_at) "
                "VALUES (?, ?, 'chat', 'old-model', 5000, 5000, 0, 1, 0, '2020-01-01T00:00:00+00:00')",
                (self.project_id, self.session["id"]),
            )
        result = usage.summary(self.project_id, 7)
        self.assertEqual(result["totals"]["total"], 1000)
        self.assertEqual(result["recorded"], 2)


class PricingTest(UsageTestBase):
    def test_save_and_clear(self) -> None:
        usage.set_pricing({"m1": {"input": 1.5, "output": 6}})
        self.assertEqual(usage.summary(self.project_id)["priced_models"], [])
        self.assertEqual(self.settings.pricing["m1"].input, 1.5)
        usage.set_pricing({})
        self.assertEqual(self.settings.pricing, {})

    def test_negative_clamped_to_zero(self) -> None:
        saved = usage.set_pricing({"m1": {"input": -3, "output": -1, "cache_read": -2}})
        self.assertEqual(saved["m1"], {"input": 0.0, "output": 0.0, "cache_read": 0.0})


class RunEventsTest(UsageTestBase):
    def test_chat_model_end_feeds_meter(self) -> None:
        from app.agent.runner import _run_events

        class FakeAgent:
            async def astream_events(self, *_args: Any, **_kwargs: Any):
                yield {
                    "event": "on_chat_model_end",
                    "data": {
                        "output": FakeMessage(
                            usage={"input_tokens": 700, "output_tokens": 130},
                            meta={"model_name": "deepseek-chat"},
                        )
                    },
                    "parent_ids": [],
                    "run_id": "r1",
                    "name": "model",
                }
                yield {
                    "event": "on_chat_model_stream",
                    "data": {"chunk": SimpleNamespace(content="你好")},
                    "parent_ids": [],
                    "run_id": "r1",
                    "name": "model",
                }

        meter = usage.UsageMeter()
        chunks: list[str] = []
        buffer: list[str] = []

        async def consume() -> None:
            async for chunk in _run_events(
                FakeAgent(), {"messages": []}, {}, buffer, [], set(), meter
            ):
                chunks.append(chunk)

        asyncio.run(consume())
        self.assertEqual(meter.as_dict()["total"], 830)
        self.assertTrue(any("你好" in item for item in chunks))


if __name__ == "__main__":
    unittest.main()
