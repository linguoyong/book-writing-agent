from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app.import_book import (
    ImportError,
    chapter_number_from_title,
    commit,
    decode_bytes,
    parse_book,
    preview,
)


class DecodeTest(unittest.TestCase):
    def test_utf8_and_bom(self) -> None:
        self.assertEqual(decode_bytes("第一章 灯".encode("utf-8")), ("第一章 灯", "utf-8"))
        text, encoding = decode_bytes(b"\xef\xbb\xbf" + "第一章 灯".encode("utf-8"))
        self.assertEqual((text, encoding), ("第一章 灯", "utf-8-sig"))

    def test_gb18030(self) -> None:
        text, encoding = decode_bytes("第一章 雾".encode("gb18030"))
        self.assertEqual(text, "第一章 雾")
        self.assertEqual(encoding, "gb18030")


class ParseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="import-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, text: str, name: str = "book.txt") -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_split_by_chapter_heading(self) -> None:
        path = self._write(
            "第一章 灯下有人\n\n北堤的灯点了三个时辰。\n\n"
            "第二章 经纬仪\n\n夏栀是踩着潮水来的。\n"
        )
        book = parse_book(path)

        self.assertEqual([c.title for c in book.chapters], ["第一章 灯下有人", "第二章 经纬仪"])
        self.assertIn("北堤", book.chapters[0].body)
        self.assertIn("夏栀", book.chapters[1].body)

    def test_long_line_is_not_heading(self) -> None:
        # 正文里以「第一章」开头、但很长的一行不能当章节标题
        path = self._write("第一章 这是正文" + "啊" * 60 + "\n\n内容\n")
        book = parse_book(path)

        self.assertEqual(len(book.chapters), 1)
        self.assertNotEqual(book.chapters[0].title, "第一章 " + "这是正文" + "啊" * 60)

    def test_fallback_split_without_headings(self) -> None:
        path = self._write("没有章节标题的正文。\n\n" + "正文段落。\n\n" * 900)
        book = parse_book(path)

        self.assertGreater(len(book.chapters), 1)
        self.assertTrue(book.chapters[0].title.endswith("节"))

    def test_preview_shape(self) -> None:
        path = self._write("第一章 灯\n\n正文一。\n\n第二章 影\n\n正文二。\n")
        data = preview(path)

        self.assertEqual(data["encoding"], "utf-8")
        self.assertEqual(len(data["chapters"]), 2)
        self.assertEqual(data["chapters"][0]["title"], "第一章 灯")
        self.assertGreater(data["chapters"][0]["chars"], 0)

    def test_missing_file_is_rejected(self) -> None:
        with self.assertRaises(ImportError):
            parse_book(self.dir / "missing.txt")

    def test_too_large_is_rejected(self) -> None:
        from app import import_book

        path = self._write("第一章 灯\n\n正文。\n")
        original = import_book.MAX_BYTES
        import_book.MAX_BYTES = 4
        try:
            with self.assertRaises(ImportError):
                parse_book(path)
        finally:
            import_book.MAX_BYTES = original


class CommitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="import-project-"))
        self.source = Path(tempfile.mkdtemp(prefix="import-src-")) / "book.txt"
        self.source.write_text(
            "第一章 初生\n\n正文一。\n\n第二章 机械系\n\n正文二。\n\n第三章 入城\n\n正文三。\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)
        shutil.rmtree(self.source.parent, ignore_errors=True)

    def test_commit_writes_files_with_title_numbers(self) -> None:
        result = commit(self.project, self.source)

        self.assertEqual(result["imported"], 3)
        files = sorted((self.project / "chapters").glob("*.md"))
        self.assertEqual(files[0].name, "0001-第一章 初生.md")
        self.assertEqual(files[2].name, "0003-第三章 入城.md")
        self.assertIn("chapter: 3", files[2].read_text(encoding="utf-8"))

    def test_commit_excludes_and_renames(self) -> None:
        result = commit(
            self.project,
            self.source,
            excluded=[1],
            titles={"0": "第一章 初生（改）"},
        )

        self.assertEqual(result["imported"], 2)
        files = sorted((self.project / "chapters").glob("*.md"))
        self.assertEqual(len(files), 2)
        self.assertIn("改", files[0].name)

    def test_second_import_does_not_overwrite(self) -> None:
        commit(self.project, self.source)
        result = commit(self.project, self.source)

        self.assertEqual(result["imported"], 3)
        self.assertEqual(len(list((self.project / "chapters").glob("*.md"))), 6)

    def test_chapter_number_from_title(self) -> None:
        self.assertEqual(chapter_number_from_title("第002章 初生"), 2)
        self.assertEqual(chapter_number_from_title("第十二回 夜谈"), 12)
        self.assertIsNone(chapter_number_from_title("序章"))


if __name__ == "__main__":
    unittest.main()
