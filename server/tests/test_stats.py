from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from app.stats import compute, count_words, sync_progress
from app.workspace import read_book_meta


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class CountWordsTest(unittest.TestCase):
    def test_whitespace_ignored(self) -> None:
        self.assertEqual(count_words("你好 世界\n\n再见"), 6)
        self.assertEqual(count_words(""), 0)


class ComputeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="stats-"))
        (self.project / "book.json").write_text(
            json.dumps({"title": "雾海灯影", "target_words": 10000, "words_per_chapter": 3000}),
            encoding="utf-8",
        )
        write(
            self.project / "manuscript" / "vol-01" / "ch-001.md",
            "---\ntitle: 第一章 灯\nchapter: 1\n---\n\n一二三 四五。\n",
        )
        write(
            self.project / "manuscript" / "vol-01" / "ch-002.md",
            "---\ntitle: 第二章 影\nchapter: 2\n---\n\n六七八。\n",
        )
        write(self.project / "manuscript" / "outline" / "vol-01.md", "大纲不计入")

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_totals(self) -> None:
        stats = compute(self.project)

        self.assertEqual(stats["chapters"], 2)
        self.assertEqual(stats["words"], 10)
        self.assertEqual(stats["avg_words"], 5)  # 5 和 4 取整
        self.assertEqual(stats["chapter"], 2)
        self.assertEqual(stats["volume"], 1)
        self.assertEqual(stats["progress"], 0.001)

    def test_cache_invalidated_on_change(self) -> None:
        first = compute(self.project)
        write(
            self.project / "manuscript" / "vol-01" / "ch-003.md",
            "---\ntitle: 第三章\nchapter: 3\n---\n\n九。\n",
        )
        second = compute(self.project)

        self.assertEqual(first["chapters"], 2)
        self.assertEqual(second["chapters"], 3)
        self.assertEqual(second["chapter"], 3)

    def test_sync_progress_updates_book_json(self) -> None:
        sync_progress(self.project)

        meta = read_book_meta(self.project)
        self.assertEqual(meta["progress"], {"volume": 1, "chapter": 2})

    def test_today_words_reset_when_day_changes_without_file_edits(self) -> None:
        self.assertGreater(compute(self.project)["today_words"], 0)

        class NextDay(date):
            @classmethod
            def today(cls):
                return date.today() + timedelta(days=1)

        with patch("app.stats.date", NextDay):
            self.assertEqual(compute(self.project)["today_words"], 0)

    def test_equal_size_quick_edit_invalidates_word_count(self) -> None:
        file = self.project / "manuscript/vol-01/ch-001.md"
        timestamp = 1_700_000_000_100_000_000
        for chapter in self.project.rglob("*.md"):
            os.utime(chapter, ns=(timestamp, timestamp))
        first = compute(self.project)
        file.write_text(
            file.read_text(encoding="utf-8").replace("一二三", "abcdefghi"), encoding="utf-8"
        )
        os.utime(file, ns=(timestamp + 10_000_000, timestamp + 10_000_000))
        self.assertEqual(compute(self.project)["words"], first["words"] + 6)

    def test_empty_project(self) -> None:
        empty = Path(tempfile.mkdtemp(prefix="stats-empty-"))
        try:
            stats = compute(empty)
            self.assertEqual(stats["chapters"], 0)
            self.assertEqual(stats["words"], 0)
            self.assertEqual(sync_progress(empty)["chapter"], 0)
        finally:
            shutil.rmtree(empty, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
