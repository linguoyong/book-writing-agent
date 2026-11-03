from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app.insight import (
    MaterialError,
    collect_graph,
    collect_timeline,
    save_material,
)
from app.kb.repository import list_entities, parse_note, save_entity
from app.text import read_text


class InsightBase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "kb").mkdir(parents=True)

    def card(self, kind: str, entity_id: str, meta: dict, body: str = "") -> None:
        save_entity(self.root, kind, entity_id, meta, body)


class GraphTest(InsightBase):
    def setUp(self) -> None:
        super().setUp()
        self.card(
            "characters",
            "lu-chen",
            {
                "name": "陆沉",
                "aliases": ["小陆"],
                "relations": [{"target": "祝先生", "label": "师徒"}],
            },
            "陆沉在苦泉村遇见祝先生。",
        )
        self.card("characters", "zhu", {"name": "祝先生"}, "祝先生教书，认识小陆。")
        self.card("factions", "kuquan", {"name": "苦泉村", "relations": ["陆沉：村民"]}, "井水发苦。")
        self.card("world", "night", {"name": "长夜"}, "世界设定，不该出现在图里。")

    def test_only_graph_kinds(self) -> None:
        data = collect_graph(self.root)
        names = {node["name"] for node in data["nodes"]}
        self.assertEqual(names, {"陆沉", "祝先生", "苦泉村"})
        self.assertEqual(data["stats"]["nodes"], 3)

    def test_relation_by_name_and_alias(self) -> None:
        data = collect_graph(self.root, include_mentions=False)
        pairs = {(edge["source"], edge["target"], edge["label"]) for edge in data["edges"]}
        self.assertIn(("characters/lu-chen", "characters/zhu", "师徒"), pairs)
        # "陆沉：村民" 用的是全角冒号，也应当解析出来
        self.assertIn(("factions/kuquan", "characters/lu-chen", "村民"), pairs)
        self.assertEqual(data["stats"]["relations"], 2)
        self.assertEqual(data["stats"]["mentions"], 0)

    def test_mentions_can_be_disabled(self) -> None:
        with_mentions = collect_graph(self.root, include_mentions=True)
        self.assertGreater(with_mentions["stats"]["mentions"], 0)
        without = collect_graph(self.root, include_mentions=False)
        self.assertEqual(without["stats"]["mentions"], 0)
        self.assertGreater(with_mentions["stats"]["nodes"], 0)

    def test_degree_counts_both_directions(self) -> None:
        data = collect_graph(self.root, include_mentions=False)
        degree = {node["name"]: node["degree"] for node in data["nodes"]}
        self.assertEqual(degree["陆沉"], 2)
        self.assertEqual(degree["苦泉村"], 1)
        self.assertEqual(degree["祝先生"], 1)

    def test_unresolved_target(self) -> None:
        self.card("characters", "wanderer", {"name": "游方", "relations": ["不存在的人:故交"]})
        data = collect_graph(self.root, include_mentions=False)
        self.assertEqual(data["stats"]["unresolved"], 1)
        self.assertEqual(data["unresolved"][0]["target"], "不存在的人")

    def test_kind_filter(self) -> None:
        data = collect_graph(self.root, kinds=["factions"], include_mentions=False)
        self.assertEqual([node["name"] for node in data["nodes"]], ["苦泉村"])

    def test_empty_project(self) -> None:
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        data = collect_graph(empty)
        self.assertEqual(data["nodes"], [])
        self.assertEqual(data["edges"], [])


class TimelineTest(InsightBase):
    def setUp(self) -> None:
        super().setUp()
        self.card(
            "characters",
            "lu-chen",
            {
                "name": "陆沉",
                "timeline": [
                    {"chapter": 3, "state": "开始学字"},
                    {"chapter": 1, "state": "在苦泉村"},
                ],
            },
        )
        self.card(
            "world",
            "night",
            {"name": "长夜", "timeline": [{"year": "第3年", "event": "昼缩定名"}, {"year": "第0年", "event": "第一夜"}]},
        )
        (self.root / "kb" / "outline").mkdir(parents=True)
        (self.root / "kb" / "outline" / "auto-timeline.md").write_text(
            "---\nname: 自动时间线\n---\n\n- 第2章 陆沉离村\n- 第1章 井水发苦\n",
            encoding="utf-8",
        )

    def test_chapter_sorted_first(self) -> None:
        data = collect_timeline(self.root)
        chapter_items = [item for item in data["items"] if item["axis"] == "chapter"]
        self.assertEqual([item["order"] for item in chapter_items], [1, 1, 2, 3])
        self.assertEqual(chapter_items[0]["text"], "在苦泉村")
        self.assertEqual(data["axes"]["chapter"], 4)

    def test_year_axis_after_chapter(self) -> None:
        data = collect_timeline(self.root)
        axes = [item["axis"] for item in data["items"]]
        self.assertEqual(axes[-2:], ["year", "year"])
        years = [item["order"] for item in data["items"] if item["axis"] == "year"]
        self.assertEqual(years, [0, 3])

    def test_auto_timeline_lines(self) -> None:
        data = collect_timeline(self.root)
        sources = {item["source_id"] for item in data["items"]}
        self.assertIn("auto-timeline", sources)
        auto = [item for item in data["items"] if item["source_id"] == "auto-timeline"]
        self.assertEqual(len(auto), 2)
        # 行首的「第N章」由分组标题表达，正文里去掉
        self.assertEqual(auto[0]["text"], "井水发苦")

    def test_outline_filter_drops_auto(self) -> None:
        data = collect_timeline(self.root, kinds=["characters"])
        self.assertTrue(all(item["source_kind"] == "characters" for item in data["items"]))
        self.assertEqual(data["total"], 2)

    def test_unknown_axis(self) -> None:
        self.card("items", "knife", {"name": "柴刀", "timeline": [{"state": "折断"}]})
        data = collect_timeline(self.root)
        unknown = [item for item in data["items"] if item["axis"] == "unknown"]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]["text"], "折断")


class MaterialTest(InsightBase):
    TEXT = "雨丝斜着扑在瓦檐上，声音细密得像有人在数钱。"

    def test_saves_card(self) -> None:
        result = save_material(
            self.root, self.TEXT, source="manuscript/vol-01/ch-001.md · 第 12 行", tags=["环境"]
        )
        self.assertFalse(result["duplicate"])
        self.assertEqual(result["meta"]["tags"], ["环境"])
        self.assertIn("ch-001.md", result["meta"]["source"])
        entities = list_entities(self.root, "materials")
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["body"].strip(), self.TEXT)

    def test_duplicate_body_returns_existing(self) -> None:
        first = save_material(self.root, self.TEXT)
        again = save_material(self.root, self.TEXT, title="换个标题")
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(len(list_entities(self.root, "materials")), 1)

    def test_multiline_duplicate_ignores_line_endings(self) -> None:
        # Windows 写盘是 CRLF，重新读出来再比时不能因此判成新素材
        text = "雨下了整宿。\n\n陆沉蹲在灶前，看最后一根柴烧成红炭。"
        first = save_material(self.root, text)
        again = save_material(self.root, text.replace("\n", "\r\n"))
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(len(list_entities(self.root, "materials")), 1)

    def test_same_title_different_body_gets_suffix(self) -> None:
        first = save_material(self.root, self.TEXT, title="雨夜")
        second = save_material(self.root, "另一种雨。", title="雨夜")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(second["id"], "雨夜-2")
        self.assertEqual(second["meta"]["name"], "雨夜（2）")

    def test_title_defaults_to_first_line(self) -> None:
        result = save_material(self.root, self.TEXT)
        self.assertLessEqual(len(result["meta"]["name"]), 16)
        self.assertTrue(result["meta"]["name"].startswith("雨丝"))

    def test_empty_and_too_long(self) -> None:
        with self.assertRaises(MaterialError):
            save_material(self.root, "   ")
        with self.assertRaises(MaterialError):
            save_material(self.root, "字" * 20001)

    def test_written_file_is_parseable(self) -> None:
        result = save_material(self.root, self.TEXT)
        meta, body = parse_note(read_text(self.root / result["file"]))
        self.assertEqual(meta["name"], result["meta"]["name"])
        self.assertEqual(body.strip(), self.TEXT)


if __name__ == "__main__":
    unittest.main()
