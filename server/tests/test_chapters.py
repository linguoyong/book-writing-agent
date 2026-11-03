from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app.chapters import ChapterError, create, next_position
from app.kb.repository import parse_note
from app.text import read_text


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ChapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="chapter-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_first_chapter(self) -> None:
        result = create(self.project)

        self.assertEqual(result["chapter"], 1)
        self.assertEqual(result["volume"], 1)
        self.assertEqual(result["path"], "manuscript/vol-01/ch-001.md")
        meta, body = parse_note(read_text(self.project / result["path"]))
        self.assertEqual(meta["chapter"], 1)
        self.assertIn("第1章", body)

    def test_next_number_follows_largest_across_volumes(self) -> None:
        write(
            self.project / "manuscript" / "vol-01" / "ch-001.md", "---\nchapter: 1\n---\n\n一。\n"
        )
        write(
            self.project / "manuscript" / "vol-02" / "ch-003.md", "---\nchapter: 7\n---\n\n七。\n"
        )

        volume, number = next_position(self.project)
        self.assertEqual((volume, number), (2, 8))

        result = create(self.project, title="雾中来客")
        self.assertEqual(result["path"], "manuscript/vol-02/ch-008.md")
        self.assertEqual(result["title"], "第8章 雾中来客")

    def test_existing_title_kept(self) -> None:
        write(
            self.project / "manuscript" / "vol-01" / "ch-001.md", "---\nchapter: 1\n---\n\n一。\n"
        )
        result = create(self.project, title="第二章 旧梦")

        self.assertEqual(result["title"], "第二章 旧梦")

    def test_existing_file_is_rejected(self) -> None:
        write(
            self.project / "manuscript" / "vol-01" / "ch-001.md", "---\nchapter: 1\n---\n\n一。\n"
        )
        write(
            self.project / "manuscript" / "vol-01" / "ch-002.md", "---\nchapter: 2\n---\n\n二。\n"
        )
        (self.project / "manuscript" / "vol-01" / "ch-003.md").write_text("占位", encoding="utf-8")

        with self.assertRaises(ChapterError):
            create(self.project)


if __name__ == "__main__":
    unittest.main()
