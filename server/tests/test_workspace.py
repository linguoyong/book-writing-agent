from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import versioning, workspace
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


class HiddenGitTest(unittest.TestCase):
    """安装包里的后端是 windowed 程序：调 git 必须带 CREATE_NO_WINDOW。

    少了这个标志，每一次 git 调用都会弹一个黑框——用户看到的就是
    「一堆窗口一闪而过」。这里守住 proc.run_hidden 真的把标志传下去了。
    """

    def _capture(self, fn) -> dict:
        calls: list[dict] = []

        def fake_run(args, **kwargs):
            calls.append({"args": args, **kwargs})
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch("subprocess.run", fake_run):
            fn()
        return calls[-1]

    def test_workspace_git_hides_console(self) -> None:
        call = self._capture(lambda: workspace._git(Path("."), "status"))

        self.assertEqual(call["args"][0], "git")
        self.assertEqual(call["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def test_versioning_git_hides_console(self) -> None:
        call = self._capture(lambda: versioning._git(Path("."), "log"))

        self.assertEqual(call["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))
