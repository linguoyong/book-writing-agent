from __future__ import annotations

import unittest

from app.agent.compaction import (
    KEEP_MESSAGES,
    SUMMARY_PROMPT,
    TRIGGER_CAP,
    compaction_plan,
)


class CompactionPlanTest(unittest.TestCase):
    """压缩参数是「质量优先」的取舍，改动要能一眼看出影响。"""

    def test_large_window_caps_at_240k(self) -> None:
        plan = compaction_plan(500_000)

        self.assertEqual(plan["trigger"], TRIGGER_CAP)
        self.assertEqual(plan["keep_messages"], KEEP_MESSAGES)
        # 截断一定早于压缩，否则第二道闸永远轮不到
        self.assertLess(plan["truncate"], plan["trigger"])
        self.assertGreater(plan["truncate"], 0)

    def test_small_window_scales_with_ratio(self) -> None:
        plan = compaction_plan(32_000)

        self.assertEqual(plan["trigger"], int(32_000 * 0.6))
        self.assertLess(plan["truncate"], plan["trigger"])

    def test_minimum_window_still_sane(self) -> None:
        plan = compaction_plan(8_000)

        self.assertGreater(plan["trigger"], 4_000)
        self.assertLess(plan["trigger"], 8_000)

    def test_prompt_is_domain_specific(self) -> None:
        # 摘要丢的必须是「通用 Agent 不需要」的东西；这几节是续写必需的
        for section in ("人物与当前状态", "设定与口径", "伏笔", "下一步"):
            self.assertIn(section, SUMMARY_PROMPT)
        self.assertEqual(SUMMARY_PROMPT.count("{messages}"), 1)


if __name__ == "__main__":
    unittest.main()
