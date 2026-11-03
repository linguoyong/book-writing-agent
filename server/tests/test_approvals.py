from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.agent.approvals import build_requests
from app.text import save_text


class ApprovalGuardTest(unittest.TestCase):
    """审批卡要记住目标文件在「中断那一刻」的 mtime。"""

    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="approval-"))
        target = self.project / "manuscript" / "vol-01" / "ch-001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        save_text(target, "旧内容\n")

    def _requests(self, args: dict) -> list[dict]:
        return build_requests(
            self.project,
            {"action_requests": [{"name": "manuscript_write", "args": args}]},
        )

    def test_existing_target_has_mtime(self) -> None:
        requests = self._requests(
            {"path": "vol-01/ch-001.md", "content": "新内容", "mode": "overwrite"}
        )

        self.assertEqual(requests[0]["target"], "manuscript/vol-01/ch-001.md")
        self.assertIsInstance(requests[0]["mtime"], int)

    def test_new_file_has_no_mtime(self) -> None:
        requests = self._requests(
            {"path": "vol-01/ch-002.md", "content": "新章", "mode": "overwrite"}
        )

        self.assertIsNone(requests[0]["mtime"])

    def test_out_of_bounds_target_has_no_mtime(self) -> None:
        requests = self._requests(
            {"path": "../../etc/passwd", "content": "x", "mode": "overwrite"}
        )

        self.assertIsNone(requests[0]["mtime"])


if __name__ == "__main__":
    unittest.main()
