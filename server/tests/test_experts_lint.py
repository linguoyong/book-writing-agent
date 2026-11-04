from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app.experts import delete_expert, expert_dir, get_expert, list_experts, save_expert
from app.kb.lint import lint_project
from app.kb.repository import save_entity
from app.text import save_text


class ExpertTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="expert-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_save_fills_defaults(self) -> None:
        saved = save_expert(
            self.project, "wuxia-editor", {"description": "武侠责编"}, "负责刀法设定。"
        )

        self.assertEqual(saved["id"], "wuxia-editor")
        self.assertEqual(saved["name"], "wuxia-editor")
        self.assertEqual(saved["avatar"], "w")
        self.assertEqual(saved["max_turns"], 50)
        self.assertIn("负责刀法设定", saved["body"])
        self.assertTrue((expert_dir(self.project) / "wuxia-editor.md").exists())

    def test_id_is_sanitized(self) -> None:
        saved = save_expert(self.project, "武侠 编辑", {"name": "武侠编辑"})

        self.assertNotIn(" ", saved["id"])
        self.assertTrue(any((expert_dir(self.project)).glob("*.md")))

    def test_list_and_get_roundtrip(self) -> None:
        save_expert(self.project, "poet", {"name": "诗人", "tags": ["诗"]})
        save_expert(self.project, "critic", {"name": "评论家"})

        ids = [item["id"] for item in list_experts(self.project)]
        self.assertIn("poet", ids)
        self.assertIn("critic", ids)
        self.assertEqual(get_expert(self.project, "poet")["name"], "诗人")
        self.assertIsNone(get_expert(self.project, "missing"))

    def test_delete_removes_file(self) -> None:
        save_expert(self.project, "poet", {"name": "诗人"})

        self.assertTrue(delete_expert(self.project, "poet"))
        self.assertFalse(delete_expert(self.project, "poet"))
        self.assertIsNone(get_expert(self.project, "poet"))

    def test_seed_experts_are_created_on_first_read(self) -> None:
        # get_expert 会先补齐内置专家：新项目打开专家页不该是空的
        self.assertIsNone(get_expert(self.project, "not-exists"))
        self.assertGreaterEqual(len(list_experts(self.project)), 1)


class LintTest(unittest.TestCase):
    """一致性检查：别称混用、未回收伏笔、时间锚点倒退。"""

    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="lint-"))
        chapters = self.project / "manuscript"
        chapters.mkdir(parents=True)
        save_text(
            chapters / "0001-a.md",
            "---\nchapter: 1\ntitle: 出发\n---\n\n林昭拔剑。小林笑了。第 5 天，雨停。\n",
        )
        save_text(
            chapters / "0002-b.md",
            "---\nchapter: 2\ntitle: 归来\n---\n\n第 3 天，他回来了。\n",
        )
        save_entity(
            self.project,
            "characters",
            "lin",
            {"name": "林昭", "aliases": ["小林"]},
            "剑客。",
        )
        save_entity(
            self.project,
            "items",
            "duanjian",
            {"name": "断剑", "status": "未回收", "planted_in": "第 1 章"},
            "断掉的剑。",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def _rules(self) -> dict[str, list[dict[str, object]]]:
        grouped: dict[str, list[dict[str, object]]] = {}
        for issue in lint_project(self.project)["issues"]:
            grouped.setdefault(str(issue["rule"]), []).append(issue)
        return grouped

    def test_alias_mix_detected_in_single_chapter(self) -> None:
        issues = self._rules()["alias_mix"]

        self.assertEqual(len(issues), 1)
        self.assertIn("0001-a", str(issues[0]["chapter"]))
        self.assertIn("林昭", str(issues[0]["message"]))

    def test_open_foreshadow_reported(self) -> None:
        issues = self._rules()["foreshadow_open"]

        self.assertEqual(len(issues), 1)
        self.assertIn("断剑", str(issues[0]["message"]))

    def test_timeline_regression_reported(self) -> None:
        issues = self._rules().get("timeline_back", [])

        self.assertEqual(len(issues), 1)
        self.assertIn("第3天", str(issues[0]["message"]))

    def test_clean_project_has_no_issues(self) -> None:
        clean = Path(tempfile.mkdtemp(prefix="lint-clean-"))
        try:
            self.assertEqual(lint_project(clean)["issues"], [])
        finally:
            shutil.rmtree(clean, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
