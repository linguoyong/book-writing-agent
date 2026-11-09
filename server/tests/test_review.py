from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import review
from app.kb.repository import dump_note, parse_note
from app.text import read_text, save_text

BODY = (
    "第3章 雨夜\n\n"
    "雨顺着屋檐往下淌，陆沉把伞收了，站在门槛外没有进去。\n\n"
    "他抬头看了一眼天色，低声问：真的要走吗？\n\n"
    "没有人回答。院子里的灯灭了一盏，风把门缝里的纸吹得沙沙响。\n\n"
    "陆沉想起三年前的那个晚上，也是这样的雨。他站在同一道门槛外，"
    "手里提着同一盏灯，只是那一次屋里有人应声。\n\n"
    "他把伞靠在墙边，抬手敲了三下门。屋里还是没有动静。"
    "雨声盖住了呼吸，他听见自己的心跳，一下一下，比雨点更沉。\n\n"
    "院子里那棵老槐树落了一地叶子，被雨水泡得发白。"
    "陆沉蹲下去捡起一片，叶脉在灯下像一张细密的地图。\n"
)


class FakeModel:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def invoke(self, prompt: str, **kwargs) -> SimpleNamespace:
        self.prompts.append(prompt)
        return SimpleNamespace(
            content=json.dumps(self.payload, ensure_ascii=False),
            usage_metadata={"input_tokens": 120, "output_tokens": 60},
            response_metadata={"model_name": "fake-reviewer"},
        )


def payload(**overrides) -> dict:
    data = {
        "dimensions": {
            "consistency": 4,
            "structure": 4,
            "pacing": 4,
            "voice": 4,
            "hook": 4,
            "redundancy": 4,
        },
        "issues": [],
        "summary": "结构完整，节奏稳。",
        "verdict": "pass",
    }
    data.update(overrides)
    return data


class ReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "manuscript" / "vol-01").mkdir(parents=True)
        (self.root / "kb").mkdir()
        self.chapter = self.root / "manuscript" / "vol-01" / "ch-003.md"
        save_text(self.chapter, dump_note({"title": "第3章 雨夜", "chapter": 3}, BODY))
        save_text(
            self.root / "book.json",
            json.dumps(
                {"title": "测试书", "progress": {"volume": 1, "chapter": 3}}, ensure_ascii=False
            ),
        )

    def run_with(self, data: dict) -> review.ReviewResult:
        fake = FakeModel(data)
        with patch.object(review, "build_chat_model", return_value=fake):
            result = review.run_review(self.root, "3")
        self.assertIsNotNone(fake.prompts)
        return result

    def test_find_chapter_by_path_and_number(self) -> None:
        relative, file = review.find_chapter(self.root, "vol-01/ch-003.md")
        self.assertEqual(relative, "vol-01/ch-003.md")
        self.assertEqual(file.name, "ch-003.md")

        relative, _ = review.find_chapter(self.root, "3")
        self.assertEqual(relative, "vol-01/ch-003.md")

        relative, _ = review.find_chapter(self.root, "ch-003.md")
        self.assertEqual(relative, "vol-01/ch-003.md")

    def test_pass_writes_front_matter_and_book_state(self) -> None:
        result = self.run_with(payload())
        self.assertEqual(result.status, "pass")
        self.assertEqual(result.round, 1)
        self.assertAlmostEqual(result.score, 4.0)

        meta, body = parse_note(read_text(self.chapter))
        self.assertEqual(meta["review"]["status"], "pass")
        self.assertEqual(meta["review"]["round"], 1)
        self.assertIn("陆沉把伞收了", body)

        book = json.loads(read_text(self.root / "book.json"))
        self.assertEqual(book["chapters"]["vol-01/ch-003.md"]["status"], "pass")

        detail = self.root / ".index" / "reviews" / "vol-01__ch-003.json"
        self.assertTrue(detail.exists())
        self.assertEqual(json.loads(read_text(detail))["status"], "pass")

    def test_p0_forces_fail_even_if_model_says_pass(self) -> None:
        result = self.run_with(
            payload(
                issues=[
                    {
                        "severity": "P0",
                        "dimension": "consistency",
                        "quote": "陆沉把伞收了",
                        "problem": "与上一章正在下雨、他没有伞的设定冲突",
                        "suggestion": "改成他借了别人的伞，或删掉收伞动作",
                    }
                ]
            )
        )
        self.assertEqual(result.status, "fail")
        self.assertEqual(len(result.p0), 1)

    def test_low_score_fails_without_p0(self) -> None:
        result = self.run_with(payload(dimensions={key: 2 for key in review.DIMENSIONS}))
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.score, 2.0)

    def test_unverifiable_quote_is_dropped(self) -> None:
        result = self.run_with(
            payload(
                issues=[
                    {
                        "severity": "P1",
                        "dimension": "pacing",
                        "quote": "陆沉把伞收了",
                        "problem": "节奏偏慢",
                        "suggestion": "压缩环境描写",
                    },
                    {
                        "severity": "P0",
                        "dimension": "structure",
                        "quote": "这句话正文里根本没有",
                        "problem": "编造的问题",
                        "suggestion": "无",
                    },
                ]
            )
        )
        self.assertEqual(len(result.issues), 1)
        self.assertEqual(result.dropped, 1)
        self.assertEqual(result.status, "pass")

    def test_round_increments_across_runs(self) -> None:
        first = self.run_with(payload())
        self.assertEqual(first.round, 1)
        second = self.run_with(payload())
        self.assertEqual(second.round, 2)

    def test_stale_after_rewrite(self) -> None:
        self.run_with(payload())
        from app.domains.book import _mark_stale

        # 模拟 Agent 保留 front-matter、只改正文
        meta, body = parse_note(read_text(self.chapter))
        save_text(self.chapter, dump_note(meta, body + "\n补了一段。\n"))
        _mark_stale(self.chapter)
        updated, _ = parse_note(read_text(self.chapter))
        self.assertEqual(updated["review"]["status"], "stale")
        self.assertIn("stale_at", updated["review"])

    def test_too_short_chapter_is_rejected(self) -> None:
        save_text(self.chapter, dump_note({"title": "第3章", "chapter": 3}, "太短了。"))
        with self.assertRaises(review.ReviewError):
            self.run_with(payload())


if __name__ == "__main__":
    unittest.main()
