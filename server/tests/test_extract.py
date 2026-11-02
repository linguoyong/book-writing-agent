from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.extract import (
    ExtractStats,
    apply_result,
    build_entity_map,
    load_state,
    normalize,
    parse_response,
    run,
)


class FakeMessage:
    def __init__(self, content: str):
        self.content = content


class FakeModel:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def invoke(self, _prompt: str) -> FakeMessage:
        self.calls += 1
        return FakeMessage(json.dumps(self.payload, ensure_ascii=False))


CHAPTER = """---
chapter: {number}
title: 第{number}章 测试
---

韩萧走进实验室，看见海拉正在记录数据。
"""


class ExtractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="extract-"))
        chapters = self.project / "chapters"
        chapters.mkdir(parents=True)
        for number in (1, 2, 3):
            (chapters / f"{number:04d}-第{number}章.md").write_text(
                CHAPTER.format(number=number), encoding="utf-8"
            )
        self.payload = {
            "characters": [
                {"name": "韩萧", "aliases": ["萧哥"], "role": "主角", "note": "机械师", "confidence": 0.9}
            ],
            "locations": [{"name": "实验室", "note": "秘密基地", "confidence": 0.8}],
            "factions": [],
            "items": [],
            "events": [{"summary": "韩萧第一次进入实验室", "characters": ["韩萧"], "importance": "major"}],
            "foreshadowing": [{"text": "海拉在记录什么数据"}],
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_normalize_caps_and_cleans(self) -> None:
        data = normalize(
            {
                "characters": [{"name": "  韩萧 ", "aliases": ["萧哥", "韩萧", "  "], "confidence": 5}]
                + [{"name": f"角色{i}"} for i in range(20)],
                "events": [{"summary": "x" * 200}],
                "foreshadowing": "不是数组",
            }
        )
        self.assertLessEqual(len(data["characters"]), 8)
        self.assertEqual(data["characters"][0]["name"], "韩萧")
        self.assertEqual(data["characters"][0]["aliases"], ["萧哥"])
        self.assertEqual(data["characters"][0]["confidence"], 1.0)
        self.assertLessEqual(len(data["events"][0]["summary"]), 80)
        self.assertEqual(data["foreshadowing"], [])

    def test_parse_response_with_fence(self) -> None:
        text = "```json\n" + json.dumps(self.payload, ensure_ascii=False) + "\n```"
        data = parse_response(text)
        self.assertEqual(data["characters"][0]["name"], "韩萧")

    def test_apply_dry_run_does_not_write(self) -> None:
        stats = apply_result(
            self.project, 1, normalize(self.payload), ExtractStats(), dry_run=True
        )

        self.assertEqual(stats.characters, 1)
        self.assertEqual(stats.events, 1)
        self.assertFalse((self.project / "kb" / "characters" / "韩萧.md").exists())
        self.assertFalse((self.project / "kb" / "outline" / "auto-timeline.md").exists())

    def test_apply_writes_cards_and_timeline(self) -> None:
        stats = apply_result(self.project, 1, normalize(self.payload), ExtractStats())

        card = self.project / "kb" / "characters" / "韩萧.md"
        self.assertTrue(card.exists())
        text = card.read_text(encoding="utf-8")
        self.assertIn("status: 待确认", text)
        self.assertIn("first_chapter: 1", text)
        timeline = (self.project / "kb" / "outline" / "auto-timeline.md").read_text(encoding="utf-8")
        self.assertIn("[事件][第1章]", timeline)
        self.assertIn("[伏笔][第1章]", timeline)
        self.assertEqual(stats.events, 1)

    def test_second_chapter_merges_alias(self) -> None:
        apply_result(self.project, 1, normalize(self.payload), ExtractStats())
        payload = {
            "characters": [
                {"name": "韩萧", "aliases": ["零号"], "role": "", "note": "", "confidence": 0.9}
            ]
        }
        entities = build_entity_map(self.project)
        stats = apply_result(self.project, 2, normalize(payload), ExtractStats(), entities=entities)

        self.assertEqual(stats.aliases, 1)
        text = (self.project / "kb" / "characters" / "韩萧.md").read_text(encoding="utf-8")
        self.assertIn("零号", text)
        self.assertEqual(len(list((self.project / "kb" / "characters").glob("*.md"))), 1)

    def test_run_is_resumable(self) -> None:
        model = FakeModel(self.payload)
        with patch("app.extract.build_chat_model", return_value=model):
            first = run(self.project, limit=2)
            second = run(self.project, limit=2)

        self.assertEqual(first["chapters"], 2)
        self.assertEqual(second["chapters"], 1)  # 只剩第 3 章
        self.assertEqual(model.calls, 3)
        state = load_state(self.project)
        self.assertEqual(len(state["done"]), 3)


if __name__ == "__main__":
    unittest.main()
