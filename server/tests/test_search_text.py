from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.rewrite import RewriteError, _clean, rewrite
from app.search_text import SearchError, replace, search


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class SearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="search-"))
        write(
            self.project / "manuscript" / "vol-01" / "ch-001.md", "灯已经点了三个时辰。\n雾漫上来。"
        )
        write(self.project / "manuscript" / "vol-01" / "ch-002.md", "雾里有人叫灯。\n灯灭了。")
        write(self.project / "chapters" / "0001.md", "第一章 灯\n\n灯火。")

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_literal_search_in_manuscript(self) -> None:
        result = search(self.project, "灯")
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["files"], 2)
        self.assertTrue(result["items"][0]["path"].startswith("manuscript/"))

    def test_scope_chapters(self) -> None:
        result = search(self.project, "灯", scope="chapters")
        self.assertEqual(result["files"], 1)
        self.assertTrue(result["items"][0]["path"].startswith("chapters/"))

    def test_path_restriction(self) -> None:
        result = search(self.project, "雾", path="manuscript/vol-01/ch-001.md")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["line"], 2)

    def test_regex_and_ignore_case(self) -> None:
        write(self.project / "manuscript" / "vol-02" / "ch-003.md", "Lamp 在这里")
        self.assertEqual(search(self.project, "lamp")["total"], 0)
        self.assertEqual(search(self.project, "lamp", ignore_case=True)["total"], 1)
        self.assertEqual(search(self.project, r"灯.{0,3}点", regex=True)["total"], 1)

    def test_empty_query_rejected(self) -> None:
        with self.assertRaises(SearchError):
            search(self.project, "  ")

    def test_bad_regex_rejected(self) -> None:
        with self.assertRaises(SearchError):
            search(self.project, "([", regex=True)

    def test_outside_path_rejected(self) -> None:
        with self.assertRaises(SearchError):
            search(self.project, "x", path="../outside.md")


class ReplaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="replace-"))
        self.file = self.project / "manuscript" / "vol-01" / "ch-001.md"
        write(self.file, "灯亮了。灯灭了。")

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_dry_run_does_not_write(self) -> None:
        result = replace(self.project, "灯", "烛", dry_run=True)
        self.assertEqual(result["total"], 2)
        self.assertIn("灯", self.file.read_text(encoding="utf-8"))

    def test_real_replace(self) -> None:
        result = replace(self.project, "灯", "烛", dry_run=False)
        self.assertEqual(result["total"], 2)
        self.assertEqual(self.file.read_text(encoding="utf-8"), "烛亮了。烛灭了。")

    def test_front_matter_is_untouched(self) -> None:
        write(self.file, "---\ntitle: 第一章 灯下有人\nchapter: 1\n---\n\n北堤的灯亮着。")
        result = replace(self.project, "灯", "烛", dry_run=False)
        text = self.file.read_text(encoding="utf-8")
        self.assertEqual(result["total"], 1)
        self.assertIn("title: 第一章 灯下有人", text)
        self.assertIn("北堤的烛亮着", text)


class FakeMessage:
    def __init__(self, content: str):
        self.content = content


class FakeModel:
    def __init__(self, content: str):
        self.content = content
        self.prompt = ""

    def invoke(self, prompt: str) -> FakeMessage:
        self.prompt = prompt
        return FakeMessage(self.content)


class RewriteTest(unittest.TestCase):
    def test_clean_strips_fence_and_label(self) -> None:
        self.assertEqual(_clean("```markdown\n灯亮了。\n```"), "灯亮了。")
        self.assertEqual(_clean("改写：灯亮了。"), "灯亮了。")

    def test_empty_selection_rejected(self) -> None:
        with self.assertRaises(RewriteError):
            rewrite("   ")

    def test_tone_requires_value(self) -> None:
        with self.assertRaises(RewriteError):
            rewrite("灯亮了。", action="tone")

    def test_rewrite_returns_text(self) -> None:
        model = FakeModel("```\n北堤的灯亮着。\n```")
        with patch("app.rewrite.build_chat_model", return_value=model):
            result = rewrite("灯亮了。", action="polish", before="上文。", after="下文。")

        self.assertEqual(result["text"], "北堤的灯亮着。")
        self.assertIn("上文", model.prompt)
        self.assertIn("下文", model.prompt)


if __name__ == "__main__":
    unittest.main()
