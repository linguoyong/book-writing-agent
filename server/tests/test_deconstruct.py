from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import deconstruct
from app.kb.repository import list_entities
from app.text import save_text

SOURCE = (
    "第1章 开端\n\n"
    "少年抬头看了看天，背起包袱走出村口。他不知道前面等着什么。\n\n"
    "第2章 进城\n\n"
    "城门下排着长队。守门的士兵看了他一眼，挥手放行。\n\n"
    "第3章 交易\n\n"
    "掌柜把算盘一推，报出一个数。少年摸了摸口袋，没有作声。\n\n"
)

GROUP_PAYLOAD = {
    "summary": "少年离村进城，第一次交易受挫。",
    "structure": {
        "goal": "进城卖掉手里的东西",
        "conflict": "钱不够",
        "turn": "掌柜压价",
        "payoff": "少年亮出底牌",
        "cliffhanger": "门外有人叫他名字",
    },
    "pacing": {"score": 4, "note": "推进干净"},
    "techniques": [
        {
            "name": "用一次失败的交易交代世界观",
            "how": "让主角在讨价还价里暴露身份和处境",
            "when": "开篇需要交代规则又不想写说明文时",
        },
        {
            "name": "章末点名制造悬念",
            "how": "在结尾让陌生人叫出主角名字",
            "when": "需要读者翻下一章时",
        },
    ],
    "entities": {
        "characters": [
            {
                "name": "沈舟",
                "aliases": ["少年"],
                "role": "主角",
                "note": "刚离村",
                "confidence": 0.9,
            }
        ],
        "factions": [],
        "items": [{"name": "旧算盘", "aliases": [], "role": "道具", "note": "", "confidence": 0.7}],
        "locations": [
            {"name": "清河镇", "aliases": [], "role": "", "note": "城门与集市", "confidence": 0.8}
        ],
        "events": [
            {"summary": "沈舟进城卖货被压价", "characters": ["沈舟"], "importance": "major"}
        ],
        "foreshadowing": [{"text": "门外有人叫出他的名字"}],
    },
}

EXPERT_PAYLOAD = {
    "expert": {
        "id": "structure-analyst",
        "name": "结构拆解师",
        "description": "拆解作品骨架与节奏",
        "tags": ["结构", "拆解"],
        "prompt": "以结构分析师的身份拆解作品",
        "body": "## 方法\n\n先看目标与阻力，再看兑现。\n",
    },
    "skill": {
        "id": "trade-scene",
        "name": "交易场景写法",
        "description": "用一次交易交代信息",
        "body": "## 步骤\n\n1. 定价\n2. 压价\n3. 亮底牌\n",
    },
}


class FakeModel:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, prompt: str) -> SimpleNamespace:
        self.calls += 1
        data = EXPERT_PAYLOAD if "拆解结果" in prompt else GROUP_PAYLOAD
        return SimpleNamespace(
            content=json.dumps(data, ensure_ascii=False),
            usage_metadata={"input_tokens": 100, "output_tokens": 50},
            response_metadata={"model_name": "fake"},
        )


class DeconstructTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "kb").mkdir()
        (self.root / "manuscript").mkdir()
        save_text(self.root / "book.json", '{"title":"拆解测试"}')
        self.source = self.root / "source.txt"
        save_text(self.source, SOURCE)

    def run_deconstruct(self, **kwargs):
        fake = FakeModel()
        with patch.object(deconstruct, "build_chat_model", return_value=fake):
            result = deconstruct.run(self.root, self.source, **kwargs)
        return result, fake

    def test_entities_and_techniques_land(self) -> None:
        result, _ = self.run_deconstruct(max_groups=1)
        self.assertEqual(result["groups"], 1)
        self.assertEqual(result["chapters"], 3)
        self.assertEqual(result["entities"], 3)

        characters = list_entities(self.root, "characters")
        self.assertEqual([item["title"] for item in characters], ["沈舟"])

        techniques = list_entities(self.root, "materials")
        self.assertEqual(len(techniques), 2)

        self.assertEqual(len(list_entities(self.root, "locations")), 1)
        self.assertEqual(len(list_entities(self.root, "items")), 1)

    def test_rerun_does_not_duplicate_techniques(self) -> None:
        self.run_deconstruct(max_groups=1)
        self.run_deconstruct(max_groups=1)
        techniques = list_entities(self.root, "materials")
        self.assertEqual(len(techniques), 2)

    def test_create_expert(self) -> None:
        result, _ = self.run_deconstruct(max_groups=1, create_expert=True)
        self.assertEqual(result["expert"]["name"], "结构拆解师")
        self.assertTrue((self.root / "experts" / "structure-analyst.md").exists())
        self.assertTrue((self.root / "skills" / "trade-scene" / "SKILL.md").exists())

        expert_file = self.root / "experts" / "structure-analyst.md"
        self.assertIn("trade-scene", expert_file.read_text(encoding="utf-8"))

    def test_missing_source(self) -> None:
        with self.assertRaises(deconstruct.DeconstructError):
            deconstruct.run(self.root, self.root / "nope.txt")


if __name__ == "__main__":
    unittest.main()
