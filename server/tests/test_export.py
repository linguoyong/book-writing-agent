from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app.export_book import ExportError, build_txt, collect, export_txt


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class CollectTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="export-"))
        write(
            self.project / "manuscript" / "vol-01" / "ch-002.md",
            "---\ntitle: 第二章 夜谈\n---\n\n夏栀来了。\n",
        )
        write(
            self.project / "manuscript" / "vol-01" / "ch-010.md",
            "---\ntitle: 第十章 决裂\n---\n\n师门决裂。\n",
        )
        write(
            self.project / "manuscript" / "vol-02" / "ch-001.md",
            "# 第一章 归途\n\n他回来了。\n",
        )
        # 大纲与内部文件都不该进正文
        write(self.project / "manuscript" / "outline" / "vol-01.md", "大纲不该出现")
        write(self.project / "manuscript" / "_notes.md", "内部笔记")

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_natural_order_and_outline_excluded(self) -> None:
        chapters = collect(self.project)
        titles = [chapter["title"] for chapter in chapters]

        self.assertEqual(titles, ["第二章 夜谈", "第十章 决裂", "第一章 归途"])

    def test_heading_title_and_body_stripped(self) -> None:
        chapters = collect(self.project)
        last = chapters[-1]

        self.assertEqual(last["title"], "第一章 归途")
        self.assertNotIn("# 第一章", last["body"])
        self.assertIn("他回来了", last["body"])

    def test_front_matter_removed(self) -> None:
        chapters = collect(self.project)
        self.assertNotIn("title:", chapters[0]["body"])

    def test_plain_title_line_is_removed(self) -> None:
        # 新建章节的正文首行就是裸标题（没有 #），导出时不能又加一遍
        write(
            self.project / "manuscript" / "vol-01" / "ch-011.md",
            "---\ntitle: 第十一章 归途\n---\n\n第十一章 归途\n\n他回来了。\n",
        )
        chapters = collect(self.project)
        target = next(item for item in chapters if item["title"] == "第十一章 归途")

        self.assertEqual(target["body"], "他回来了。")

    def test_title_falls_back_to_filename(self) -> None:
        write(self.project / "manuscript" / "vol-03" / "003-无题.md", "正文。")
        chapters = collect(self.project)

        self.assertEqual(chapters[-1]["title"], "无题")


class BuildTxtTest(unittest.TestCase):
    def test_header_and_separator(self) -> None:
        chapters = [{"title": "第一章", "body": "正文一。", "chars": 3}]
        text = build_txt(chapters, book_title="雾海灯影", author="示例作者")

        self.assertTrue(text.startswith("雾海灯影\n作者：示例作者"))
        self.assertIn("第一章\n\n正文一。", text)

    def test_toc_is_optional(self) -> None:
        chapters = [{"title": "第一章", "body": "正文。", "chars": 2}]
        self.assertNotIn("目录", build_txt(chapters))
        self.assertIn("目录", build_txt(chapters, include_toc=True))

    def test_multi_volume_headings(self) -> None:
        chapters = [
            {"title": "第一章", "body": "甲", "chars": 1, "volume": "vol-01"},
            {"title": "第二章", "body": "乙", "chars": 1, "volume": "vol-02"},
        ]
        text = build_txt(chapters)

        self.assertIn("第1卷", text)
        self.assertIn("第2卷", text)

    def test_single_volume_has_no_heading(self) -> None:
        chapters = [{"title": "第一章", "body": "甲", "chars": 1, "volume": "vol-01"}]

        self.assertNotIn("第1卷", build_txt(chapters))

    def test_empty_raises(self) -> None:
        with self.assertRaises(ExportError):
            build_txt([])


class ExportFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="export-file-"))
        write(
            self.project / "manuscript" / "vol-01" / "ch-001.md",
            "---\ntitle: 第一章\n---\n\n第一段。\n\n第二段。\n",
        )
        (self.project / "book.json").write_text(
            '{"title": "雾海灯影", "author": "示例作者"}', encoding="utf-8"
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_default_path_and_encoding(self) -> None:
        result = export_txt(self.project)

        path = Path(result["path"])
        self.assertTrue(path.exists())
        self.assertEqual(path.parent.name, "exports")
        self.assertTrue(path.name.endswith(".txt"))
        content = path.read_text(encoding="utf-8")
        self.assertIn("雾海灯影", content)
        self.assertIn("第一段。", content)

    def test_custom_path_gets_txt_suffix(self) -> None:
        target = self.project / "out" / "成稿"
        result = export_txt(self.project, target=str(target))

        self.assertTrue(result["path"].endswith("成稿.txt"))
        self.assertTrue(Path(result["path"]).exists())

    def test_gb18030(self) -> None:
        result = export_txt(self.project, target=str(self.project / "gbk.txt"), encoding="gb18030")

        raw = Path(result["path"]).read_bytes()
        self.assertIn("第一段", raw.decode("gb18030"))

    def test_empty_project_raises(self) -> None:
        empty = Path(tempfile.mkdtemp(prefix="export-empty-"))
        try:
            with self.assertRaises(ExportError):
                export_txt(empty)
        finally:
            shutil.rmtree(empty, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
