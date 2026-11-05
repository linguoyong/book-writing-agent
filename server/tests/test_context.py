from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app import context, memory
from app.kb.repository import save_entity
from app.text import save_text


class AssembleTest(unittest.TestCase):
    """分层装配：预算、截断、记忆注入顺序。"""

    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="ctx-"))
        save_text(self.project / "AGENTS.md", "# 项目记忆\n\n- 章节标题极简\n")
        save_entity(self.project, "characters", "lin", {"name": "林昭"}, "青云山弟子。")
        chapters = self.project / "chapters"
        chapters.mkdir(parents=True)
        save_text(chapters / "0001-a.md", "---\nchapter: 1\ntitle: 初入山门\n---\n\n正文。\n")
        # 记忆目录是模块级全局：指到临时目录，别碰真实用户文件
        self._memory_dir = memory.MEMORY_DIR
        memory.MEMORY_DIR = Path(tempfile.mkdtemp(prefix="ctx-mem-"))

    def tearDown(self) -> None:
        memory.MEMORY_DIR = self._memory_dir
        shutil.rmtree(self.project, ignore_errors=True)

    def _layers(self, bundle: context.ContextBundle) -> list[str]:
        return [item.layer for item in bundle.items]

    def test_layers_keep_expected_order(self) -> None:
        bundle = context.assemble(self.project)

        self.assertEqual(
            self._layers(bundle),
            ["identity", "persona", "domain", "user", "long", "project", "skills", "runtime"],
        )
        self.assertTrue(bundle.system_prompt.startswith(context.IDENTITY.splitlines()[0]))
        self.assertTrue(bundle.fingerprint.startswith("book:-:"))

    def test_project_memory_is_injected(self) -> None:
        memory.append("project", "禁用「不是 A，而是 B」句式", self.project)

        bundle = context.assemble(self.project)
        project_item = next(item for item in bundle.items if item.layer == "project")

        self.assertIn("不是 A，而是 B", bundle.system_prompt)
        self.assertEqual(project_item.source, "AGENTS.md")
        self.assertFalse(project_item.truncated)

    def test_over_budget_layer_is_clipped_and_flagged(self) -> None:
        limit = context.LIMITS["project"]
        memory.write("project", "开头" + "冗长的设定说明。" * (limit // 4), self.project)

        bundle = context.assemble(self.project)
        item = next(entry for entry in bundle.items if entry.layer == "project")

        self.assertTrue(item.truncated)
        self.assertGreater(item.chars, limit)
        self.assertIn("已按层预算截断", bundle.system_prompt)
        self.assertLess(bundle.total_chars, sum(context.LIMITS.values()))

    def test_memory_keeps_tail_when_clipped(self) -> None:
        # 记忆是往尾部追加的：截断后最新的那条必须还在，否则新记忆永远注入不进去
        limit = context.LIMITS["project"]
        memory.write("project", "很久以前的设定。" * (limit // 3), self.project)
        memory.append("project", "最新一条：主角在第 30 章断剑", self.project)

        bundle = context.assemble(self.project)

        self.assertIn("最新一条：主角在第 30 章断剑", bundle.system_prompt)

    def test_readonly_session_says_no_write(self) -> None:
        bundle = context.assemble(self.project, readonly=True)

        self.assertIn("这是一次侧问", bundle.system_prompt)

    def test_references_block_carries_entity_body(self) -> None:
        bundle = context.assemble(
            self.project,
            references=[{"type": "entity", "kind": "characters", "id": "lin", "name": "林昭"}],
        )
        item = next(entry for entry in bundle.items if entry.layer == "references")

        self.assertTrue(item.included)
        self.assertIn("青云山弟子", bundle.system_prompt)

    def test_two_long_references_are_both_kept(self) -> None:
        # 单项从 4000 收到 1500 就是为了这个：@ 两个长文件时第二个不能被腰斩
        save_text(self.project / "a.md", "甲" * 5000)
        save_text(self.project / "b.md", "乙" * 5000)

        bundle = context.assemble(
            self.project,
            references=[
                {"type": "file", "path": "a.md", "name": "a"},
                {"type": "file", "path": "b.md", "name": "b"},
            ],
        )

        self.assertIn("甲", bundle.system_prompt)
        self.assertIn("乙", bundle.system_prompt)
        self.assertIn("引用内容过长", bundle.system_prompt)
        item = next(entry for entry in bundle.items if entry.layer == "references")
        self.assertLessEqual(item.chars, context.LIMITS["references"])

    def test_blocked_reference_is_not_inlined(self) -> None:
        # .env 在只读边界外：占位说明要给出来，但内容一个字都不能进上下文
        save_text(self.project / ".env", "SECRET=1\n")
        bundle = context.assemble(
            self.project,
            references=[{"type": "file", "path": ".env", "name": ".env"}],
        )
        self.assertIn("该路径不允许引用", bundle.system_prompt)
        self.assertNotIn("SECRET=1", bundle.system_prompt)

    def test_fingerprint_changes_with_content(self) -> None:
        before = context.assemble(self.project).fingerprint
        memory.append("project", "新增一条约定", self.project)
        after = context.assemble(self.project).fingerprint

        self.assertNotEqual(before, after)


class ClipLayerTest(unittest.TestCase):
    def test_non_tail_layer_keeps_head(self) -> None:
        text = "开头" + "x" * 200
        clipped = context._clip_layer(text, 50, "domain")

        self.assertTrue(clipped.startswith("开头"))
        self.assertLessEqual(len(clipped), 51)

    def test_tail_layer_keeps_recent(self) -> None:
        text = "旧内容" * 40 + "\n最新一条"
        clipped = context._clip_layer(text, 40, "project")

        self.assertIn("最新一条", clipped)
        self.assertLessEqual(len(clipped), 41)


if __name__ == "__main__":
    unittest.main()
