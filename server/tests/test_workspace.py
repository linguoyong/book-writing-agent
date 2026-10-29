from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app.workspace import safe_join


class SafeJoinTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="safe-join-"))
        self.project = self.root / "book"
        (self.project / "manuscript").mkdir(parents=True)
        (self.root / "book-evil").mkdir()
        (self.root / "book-evil" / "secret.txt").write_text("x", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_normal_path(self) -> None:
        target = safe_join(self.project, "manuscript/ch-001.md")
        self.assertEqual(target, (self.project / "manuscript" / "ch-001.md").resolve())

    def test_internal_dotdot_stays_inside(self) -> None:
        target = safe_join(self.project, "manuscript/../kb/x.md")
        self.assertEqual(target, (self.project / "kb" / "x.md").resolve())

    def test_sibling_prefix_escape_is_rejected(self) -> None:
        # 回归：字符串 startswith 会放行 ../book-evil（前缀相同）
        with self.assertRaises(ValueError):
            safe_join(self.project, "../book-evil/secret.txt")

    def test_parent_escape_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            safe_join(self.project, "../../etc/passwd")

    def test_absolute_path_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            safe_join(self.project, str(self.root / "outside.txt"))


if __name__ == "__main__":
    unittest.main()
