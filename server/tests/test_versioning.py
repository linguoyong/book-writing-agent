from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.versioning import (
    VersionError,
    commit_all,
    file_diff,
    files,
    log,
    read_file_at,
    restore,
)


def git(project: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=project,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} 失败：{result.stderr}")
    return result.stdout.strip()


class VersioningTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "写作 Agent")
        git(self.root, "config", "user.email", "book@local")
        self.chapter = self.root / "manuscript" / "vol-01" / "ch-001.md"
        self.chapter.parent.mkdir(parents=True)
        self.chapter.write_text("# 第1章\n\n雨下了整宿。\n", encoding="utf-8", newline="")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "初始化")

    def commit(self, message: str) -> str:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", message)
        return git(self.root, "rev-parse", "HEAD")


class LogTest(VersioningTestBase):
    def test_newest_first(self) -> None:
        self.chapter.write_text("# 第1章\n\n雨停了。\n", encoding="utf-8", newline="")
        self.commit("改写第一节")
        items = log(self.root)
        self.assertEqual([item["message"] for item in items], ["改写第一节", "初始化"])
        self.assertTrue(all(len(item["short"]) >= 7 for item in items))
        self.assertEqual(items[0]["author"], "写作 Agent")

    def test_limit(self) -> None:
        for index in range(3):
            self.chapter.write_text(f"# 第1章\n\n第 {index} 稿。\n", encoding="utf-8", newline="")
            self.commit(f"第{index}次修改")
        self.assertEqual(len(log(self.root, limit=2)), 2)
        self.assertEqual(len(log(self.root, limit=0)), 1)

    def test_missing_repo_returns_empty(self) -> None:
        plain = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, plain, ignore_errors=True)
        self.assertEqual(log(plain), [])


class FilesTest(VersioningTestBase):
    def test_modified_and_added(self) -> None:
        self.chapter.write_text("# 第1章\n\n雨停了。\n", encoding="utf-8", newline="")
        extra = self.root / "manuscript" / "vol-01" / "ch-002.md"
        extra.write_text("# 第2章\n", encoding="utf-8", newline="")
        head = self.commit("补第二章")
        items = {item["path"]: item["status"] for item in files(self.root, head)}
        self.assertEqual(items["manuscript/vol-01/ch-001.md"], "M")
        self.assertEqual(items["manuscript/vol-01/ch-002.md"], "A")

    def test_bad_hash(self) -> None:
        for bad in ("", "HEAD", "../etc", "zzzzzzz"):
            with self.subTest(commit=bad):
                with self.assertRaises(VersionError):
                    files(self.root, bad)


class FileDiffTest(VersioningTestBase):
    def test_diff_shows_both_sides(self) -> None:
        self.chapter.write_text("# 第1章\n\n雨停了。\n", encoding="utf-8", newline="")
        head = self.commit("改写第一节")
        diff = file_diff(self.root, head, "manuscript/vol-01/ch-001.md")["diff"]
        self.assertIn("-雨下了整宿。", diff)
        self.assertIn("+雨停了。", diff)

    def test_path_traversal(self) -> None:
        head = git(self.root, "rev-parse", "HEAD")
        for bad in ("../outside.md", "manuscript/../../x.md", ""):
            with self.subTest(path=bad):
                with self.assertRaises(VersionError):
                    file_diff(self.root, head, bad)


class ReadFileAtTest(VersioningTestBase):
    def test_reads_old_content(self) -> None:
        original = git(self.root, "rev-parse", "HEAD")
        self.chapter.write_text("# 第1章\n\n雨停了。\n", encoding="utf-8", newline="")
        self.commit("改写第一节")
        content = read_file_at(self.root, original, "manuscript/vol-01/ch-001.md")["content"]
        self.assertIn("雨下了整宿。", content)
        self.assertNotIn("雨停了。", content)

    def test_missing_file(self) -> None:
        head = git(self.root, "rev-parse", "HEAD")
        with self.assertRaises(VersionError):
            read_file_at(self.root, head, "manuscript/vol-01/ch-999.md")


class RestoreTest(VersioningTestBase):
    def test_restore_writes_back_and_commits(self) -> None:
        original = git(self.root, "rev-parse", "HEAD")
        self.chapter.write_text("# 第1章\n\n雨停了。\n", encoding="utf-8", newline="")
        self.commit("改写第一节")
        before = log(self.root)

        result = restore(self.root, original, "manuscript/vol-01/ch-001.md")
        self.assertEqual(result["restored_from"], original[:7])

        now = self.chapter.read_text(encoding="utf-8")
        self.assertIn("雨下了整宿。", now)
        self.assertNotIn("雨停了。", now)

        after = log(self.root)
        self.assertEqual(len(after), len(before) + 1)
        self.assertIn("恢复 manuscript/vol-01/ch-001.md", after[0]["message"])
        self.assertEqual(after[0]["short"], result["commit"])

    def test_restore_is_a_new_commit_not_rewrite(self) -> None:
        original = git(self.root, "rev-parse", "HEAD")
        self.chapter.write_text("# 第1章\n\n雨停了。\n", encoding="utf-8", newline="")
        edited = self.commit("改写第一节")
        restore(self.root, original, "manuscript/vol-01/ch-001.md")
        history = [item["hash"] for item in log(self.root)]
        self.assertIn(edited, history)
        self.assertEqual(len(history), 3)

    def test_restore_same_content_is_noop(self) -> None:
        # 恢复成和当前一致的内容时没有可提交的改动，按成功处理而不是报错
        head = git(self.root, "rev-parse", "HEAD")
        result = restore(self.root, head, "manuscript/vol-01/ch-001.md")
        self.assertTrue(result["unchanged"])
        self.assertEqual(len(log(self.root)), 1)


class CommitAllTest(VersioningTestBase):
    def test_commit_all_with_changes(self) -> None:
        self.chapter.write_text("# 第1章\n\n雨停了。\n", encoding="utf-8", newline="")
        result = commit_all(self.root, "保存进度")
        self.assertIsNotNone(result["commit"])
        self.assertEqual(result["changed"], 1)
        self.assertEqual(log(self.root)[0]["message"], "保存进度")

    def test_commit_all_without_changes(self) -> None:
        self.assertIsNone(commit_all(self.root)["commit"])


if __name__ == "__main__":
    unittest.main()
