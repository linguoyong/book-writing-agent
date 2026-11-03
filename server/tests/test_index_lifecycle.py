from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import EmbeddingSettings
from app.kb.repository import delete_entity, save_entity
from app.kb.search import KbIndex
from app.text import save_text


class IndexLifecycleTest(unittest.TestCase):
    """卡片增删改、章节删除之后，索引不能留下幽灵条目。"""

    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp())
        save_entity(
            self.project,
            "characters",
            "linzhao",
            {"name": "林昭", "first_chapter": 500},
            "剑客，剑名照夜。",
        )
        save_entity(
            self.project,
            "characters",
            "shenyan",
            {"name": "沈砚", "first_chapter": 3},
            "书生，住在苦泉村。",
        )
        chapters = self.project / "chapters"
        chapters.mkdir(parents=True, exist_ok=True)
        save_text(
            chapters / "0003-x.md",
            "---\nchapter: 3\ntitle: 第三章\n---\n\n沈砚在苦泉村遇见了林昭。\n",
        )
        self.index = KbIndex(self.project, EmbeddingSettings())
        self.index.rebuild(embed=False)

    def test_rebuild_counts_entities_and_chapters(self) -> None:
        self.assertEqual(self.index.stats()["chunks"], 3)

    def test_chapter_limit_applies_to_entity_routing(self) -> None:
        # 林昭 first_chapter=500：写第 10 章时不该被实体路由捞回来
        self.assertEqual(self.index.search("林昭", kinds=["characters"], chapter_limit=10), [])
        later = self.index.search("林昭", kinds=["characters"], chapter_limit=600)
        self.assertEqual([item["ref"] for item in later], ["linzhao"])

    def test_remove_entity_clears_chunks(self) -> None:
        self.assertTrue(delete_entity(self.project, "characters", "linzhao"))
        self.assertEqual(self.index.remove_entity("characters", "linzhao"), 1)
        self.assertEqual(self.index.search("林昭", kinds=["characters"]), [])
        self.assertEqual(self.index.stats()["chunks"], 2)

    def test_remove_source_clears_deleted_chapter(self) -> None:
        self.assertEqual(self.index.remove_source("chapters/0003-x.md"), 1)
        self.assertEqual(self.index.stats()["chunks"], 2)
        self.assertEqual(self.index.remove_source("chapters/0003-x.md"), 0)

    def test_rename_source_keeps_chunks(self) -> None:
        self.assertEqual(self.index.rename_source("chapters/0003-x.md", "chapters/0003-y.md"), 1)
        self.assertEqual(self.index.stats()["chunks"], 3)
        self.assertEqual(self.index.remove_source("chapters/0003-y.md"), 1)


if __name__ == "__main__":
    unittest.main()
