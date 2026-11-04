from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app import memory
from app.text import save_text


class MemoryTest(unittest.TestCase):
    """记忆是纯文件：读写、去重、按日分组、条目化管理。"""

    def setUp(self) -> None:
        self._dir = memory.MEMORY_DIR
        memory.MEMORY_DIR = Path(tempfile.mkdtemp(prefix="mem-"))
        self.project = Path(tempfile.mkdtemp(prefix="mem-proj-"))
        memory.ensure_files(self.project)

    def tearDown(self) -> None:
        memory.MEMORY_DIR = self._dir
        shutil.rmtree(self.project, ignore_errors=True)

    def test_ensure_files_seeds_all_scopes(self) -> None:
        self.assertTrue(memory.memory_path("user").exists())
        self.assertTrue(memory.memory_path("long").exists())
        self.assertTrue(memory.memory_path("project", self.project).exists())
        self.assertIn("AGENTS.md", memory.memory_path("project", self.project).name)

    def test_write_then_read_roundtrip(self) -> None:
        memory.write("project", "## 写作约定\n- 段落单空行", self.project)

        self.assertEqual(memory.read("project", self.project).strip(), "## 写作约定\n- 段落单空行")

    def test_append_is_idempotent(self) -> None:
        self.assertTrue(memory.append("project", "禁用 AI 指纹句式", self.project))
        self.assertEqual(memory.append("project", "禁用  AI 指纹句式", self.project), "")

        self.assertEqual(memory.read("project", self.project).count("禁用 AI 指纹句式"), 1)

    def test_append_with_source_is_traceable(self) -> None:
        memory.append("long", "主角断剑在第 30 章", self.project, source="会话 42")

        items = memory.entries("long")
        self.assertEqual(items[-1]["text"], "主角断剑在第 30 章")
        self.assertEqual(items[-1]["source"], "会话 42")

    def test_long_memory_groups_by_date(self) -> None:
        memory.append("long", "第一条", self.project)
        memory.append("long", "第二条", self.project)

        text = memory.read("long")
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertEqual(text.count(f"## {today}"), 1)
        self.assertEqual([item["date"] for item in memory.entries("long")][-2:], [today, today])

    def test_delete_entry_removes_exact_line(self) -> None:
        memory.append("project", "要删掉的一条", self.project)
        memory.append("project", "要留下的一条", self.project)

        self.assertTrue(memory.delete_entry("project", "要删掉的一条", self.project))
        self.assertNotIn("要删掉的一条", memory.read("project", self.project))
        self.assertIn("要留下的一条", memory.read("project", self.project))
        self.assertFalse(memory.delete_entry("project", "不存在的一条", self.project))

    def test_append_empty_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            memory.append("project", "   ", self.project)

    def test_unknown_scope_raises(self) -> None:
        with self.assertRaises(ValueError):
            memory.memory_path("nope")
        with self.assertRaises(ValueError):
            memory.read("project")

    def test_set_project_words_updates_existing_line(self) -> None:
        memory.set_project_words(self.project, 3000)
        memory.set_project_words(self.project, 4500)

        text = memory.read("project", self.project)
        self.assertEqual(text.count("- 每章目标约"), 1)
        self.assertIn("- 每章目标约 4500 字", text)

    def test_set_project_words_without_section_appends(self) -> None:
        save_text(memory.memory_path("project", self.project), "# 空壳\n")
        memory.set_project_words(self.project, 6000)

        text = memory.read("project", self.project)
        self.assertIn("## 写作约定", text)
        self.assertIn("- 每章目标约 6000 字", text)

    def test_daily_log_appends_with_time(self) -> None:
        memory.daily_log("跑完增量索引的验证", tag="索引")

        today = datetime.now().strftime("%Y-%m-%d")
        text = (memory.MEMORY_DIR / f"{today}.md").read_text(encoding="utf-8")
        self.assertIn("[索引] 跑完增量索引的验证", text)

        status = {item["scope"]: item for item in memory.status(self.project)}
        self.assertIn("daily", status)
        self.assertGreater(status["daily"]["chars"], 0)


if __name__ == "__main__":
    unittest.main()
