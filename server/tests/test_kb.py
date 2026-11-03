from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app.config import EmbeddingSettings
from app.kb.repository import save_entity, state_at, trim_meta
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


class TimelineTest(unittest.TestCase):
    META = {
        "name": "沈砚",
        "timeline": [
            {"chapter": 1, "state": {"location": "北堤", "mood": "疲惫"}},
            {"chapter": 12, "state": {"location": "旧灯塔", "mood": "决绝"}},
            {"chapter": 30, "state": {"location": "雾港", "mood": "平静"}},
        ],
    }

    def test_state_at_uses_latest_not_after_chapter(self) -> None:
        self.assertEqual(state_at(self.META, 5)["chapter"], 1)
        self.assertEqual(state_at(self.META, 12)["state"]["location"], "旧灯塔")
        self.assertEqual(state_at(self.META, 99)["chapter"], 30)

    def test_state_at_returns_none_before_first(self) -> None:
        self.assertIsNone(state_at({"timeline": [{"chapter": 5, "state": {}}]}, 1))

    def test_trim_meta_hides_future(self) -> None:
        trimmed = trim_meta(self.META, 12)
        chapters = [entry["chapter"] for entry in trimmed["timeline"]]
        self.assertEqual(chapters, [1, 12])

    def test_trim_meta_without_chapter_is_noop(self) -> None:
        self.assertEqual(trim_meta(self.META, 0), self.META)


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


class EntityRoutingTest(unittest.TestCase):
    """查询里点名了实体时，该实体应排到最前，并能按别名命中。"""

    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="kb-route-"))
        save_entity(
            self.project,
            "characters",
            "lin",
            {"name": "林昭", "aliases": ["小林", "老沈"]},
            "## 性格\n沉默寡言，认死理。",
        )
        # 总纲里反复出现「林昭」，BM25 会把它顶到第一
        save_entity(
            self.project,
            "outline",
            "vol1",
            {"name": "第一卷总纲"},
            "## 主线\n" + "林昭与师门决裂，林昭下山，林昭入城。" * 20,
        )
        save_entity(self.project, "characters", "deng", {"name": "灯"}, "## 说明\n会亮的灯。")
        self.index = KbIndex(self.project, EmbeddingSettings())
        self.index.rebuild()

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_named_entity_ranks_first(self) -> None:
        hits = self.index.search("林昭的性格是什么样", top_k=5)

        self.assertTrue(hits)
        self.assertEqual(hits[0]["ref"], "lin")
        self.assertTrue(hits[0].get("routed"))

    def test_alias_matches_entity(self) -> None:
        hits = self.index.search("老沈最近在做什么", top_k=5)

        self.assertEqual(hits[0]["ref"], "lin")

    def test_single_char_name_matches_by_char(self) -> None:
        hits = self.index.search("灯光很暗", top_k=5)

        self.assertTrue([hit for hit in hits if hit["ref"] == "deng" and hit.get("routed")])

    def test_stopword_never_routes(self) -> None:
        save_entity(self.project, "characters", "shi", {"name": "是"}, "## 说明\n只是个测试。")
        self.index.rebuild()

        hits = self.index.search("这是什么", top_k=5)

        self.assertFalse([hit for hit in hits if hit["ref"] == "shi" and hit.get("routed")])

    def test_routing_respects_kind_filter(self) -> None:
        hits = self.index.search("林昭", kinds=["outline"], top_k=5)

        self.assertTrue(all(hit["kind"] == "outline" for hit in hits))


if __name__ == "__main__":
    unittest.main()
