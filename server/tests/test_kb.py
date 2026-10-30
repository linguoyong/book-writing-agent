from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app.config import EmbeddingSettings
from app.kb.repository import save_entity
from app.kb.search import KbIndex, _chapter_number, _normalize


class IndexBaselineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="kb-test-"))
        (self.project / "chapters").mkdir(parents=True)
        (self.project / "chapters" / "0001-第一章.md").write_text(
            "第一章 青云山\n\n林昭站在青云山的石阶上，风雪扑面。", encoding="utf-8"
        )
        self.index = KbIndex(self.project, EmbeddingSettings())

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_no_baseline_initially(self) -> None:
        self.assertFalse(self.index.has_baseline())

    def test_first_incremental_write_indexes_existing_content(self) -> None:
        # 回归：旧逻辑只写这一条，chunks>0 后永不重建，旧章节永远搜不到
        save_entity(self.project, "characters", "lin", {"name": "林昭"}, "青云山弟子。")
        self.index.reindex_entity("characters", "lin")

        self.assertTrue(self.index.has_baseline())
        hits = self.index.search("青云山")
        self.assertTrue(any(hit["kind"] == "chapters" for hit in hits))
        self.assertTrue(any(hit["title"] == "林昭" for hit in hits))

    def test_second_write_stays_incremental(self) -> None:
        save_entity(self.project, "characters", "lin", {"name": "林昭"}, "青云山弟子。")
        self.index.reindex_entity("characters", "lin")
        before = self.index.stats()["chunks"]

        save_entity(self.project, "characters", "su", {"name": "苏晴"}, "落霞城医女。")
        self.index.reindex_entity("characters", "su")

        self.assertEqual(self.index.stats()["chunks"], before + 1)
        self.assertTrue(self.index.search("苏晴"))


class NormalizeTest(unittest.TestCase):
    def test_relative_score_and_raw_score(self) -> None:
        items = [{"id": "a", "raw": 10.0}, {"id": "b", "raw": 5.0}]
        result = _normalize(items, "raw", top_k=10, threshold=0.0)

        self.assertEqual(result[0]["score"], 1.0)
        self.assertEqual(result[0]["raw_score"], 10.0)
        self.assertEqual(result[1]["score"], 0.5)

    def test_threshold_filters_relative_score(self) -> None:
        items = [{"id": "a", "raw": 10.0}, {"id": "b", "raw": 5.0}]
        result = _normalize(items, "raw", top_k=10, threshold=0.6)
        self.assertEqual([item["id"] for item in result], ["a"])


class ChapterNumberTest(unittest.TestCase):
    def test_meta_number_wins(self) -> None:
        self.assertEqual(_chapter_number({"chapter": 12}, "0001-第一章"), 12)

    def test_falls_back_to_filename(self) -> None:
        self.assertEqual(_chapter_number({}, "0007-第七章"), 7)

    def test_unknown_returns_zero(self) -> None:
        self.assertEqual(_chapter_number({}, "序章"), 0)


class EntityChunkSplitTest(unittest.TestCase):
    """长角色卡按小节拆分，且增量写入不会留下重复切片。"""

    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="kb-split-"))
        self.index = KbIndex(self.project, EmbeddingSettings())
        self.body = (
            "## 外貌\n" + "眉目清冷，一身青衣。" * 60 + "\n"
            "## 性格\n" + "沉默寡言，认死理。" * 60 + "\n"
            "## 成长路线\n" + "十二岁入门，十八岁筑基。" * 60
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def _chunk_ids(self) -> list[str]:
        return [item["id"] for item in self.index.list_chunks(kind="characters")["items"]]

    def test_long_card_splits_into_sections(self) -> None:
        save_entity(self.project, "characters", "lin", {"name": "林昭"}, self.body)
        self.index.rebuild()

        ids = self._chunk_ids()
        self.assertGreaterEqual(len(ids), 2)
        self.assertIn("characters:lin:0", ids)

    def test_short_card_stays_single_chunk(self) -> None:
        save_entity(self.project, "characters", "su", {"name": "苏晴"}, "落霞城医女。")
        self.index.rebuild()

        self.assertEqual(self._chunk_ids(), ["characters:su"])

    def test_reindex_replaces_whole_group(self) -> None:
        save_entity(self.project, "characters", "lin", {"name": "林昭"}, self.body)
        self.index.rebuild()
        before = self._chunk_ids()

        self.index.reindex_entity("characters", "lin")

        self.assertEqual(self._chunk_ids(), before)

    def test_search_dedupes_split_sections(self) -> None:
        save_entity(self.project, "characters", "lin", {"name": "林昭"}, self.body)
        self.index.rebuild()

        hits = self.index.search("眉目清冷 沉默寡言 十二岁入门", kinds=["characters"], top_k=10)

        self.assertEqual(len([hit for hit in hits if hit["ref"] == "lin"]), 1)


if __name__ == "__main__":
    unittest.main()
