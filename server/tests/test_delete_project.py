from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import db, security
from app.api import routes
from app.main import app


class PurgeDirectoryTest(unittest.TestCase):
    """删目录要能扛住 Windows 上短暂的占用（杀软扫描、索引服务）。"""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="purge-"))
        self.target = self.root / "book"
        (self.target / "chapters").mkdir(parents=True)
        (self.target / "chapters" / "0001.md").write_text("# 一\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_retries_then_succeeds(self) -> None:
        real = shutil.rmtree
        calls = {"n": 0}

        def flaky(path, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError("被占用")
            return real(path, **kwargs)

        with mock.patch("app.api.routes.shutil.rmtree", side_effect=flaky):
            routes._purge_directory(self.target)

        self.assertFalse(self.target.exists())
        self.assertEqual(calls["n"], 3)

    def test_gives_up_after_attempts(self) -> None:
        with mock.patch(
            "app.api.routes.shutil.rmtree", side_effect=PermissionError("被占用")
        ) as patched:
            with self.assertRaises(OSError):
                routes._purge_directory(self.target, attempts=2)

        self.assertEqual(patched.call_count, 2)
        self.assertTrue(self.target.exists())


class DeleteProjectRouteTest(unittest.TestCase):
    """删不掉目录时必须整单回滚：记录不能先没。"""

    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp(prefix="dbhome-"))
        self._db_file = db.DB_FILE
        db.DB_FILE = self.home / "app.db"
        db.init_db()

        self._disabled = security._DISABLED
        security._DISABLED = True
        self.client = TestClient(app)

        self.project_dir = self.home / "books" / "demo"
        self.project_dir.mkdir(parents=True)
        (self.project_dir / "book.json").write_text("{}", encoding="utf-8")
        self.project = db.create_project("demo", str(self.project_dir))
        db.create_session(self.project["id"], "第一段对话")

    def tearDown(self) -> None:
        db.DB_FILE = self._db_file
        security._DISABLED = self._disabled
        shutil.rmtree(self.home, ignore_errors=True)

    def _url(self, purge: bool = True) -> str:
        return f"/api/projects/{self.project['id']}?purge={'true' if purge else 'false'}"

    def test_purge_failure_keeps_records(self) -> None:
        with mock.patch.object(routes, "_purge_directory", side_effect=PermissionError("被占用")):
            response = self.client.delete(self._url())

        self.assertEqual(response.status_code, 409)
        self.assertIn("目录删不掉", response.json()["detail"])
        self.assertIsNotNone(db.get_project(self.project["id"]))
        self.assertEqual(len(db.list_sessions(self.project["id"])), 1)
        self.assertTrue(self.project_dir.exists())

    def test_purge_success_removes_both(self) -> None:
        response = self.client.delete(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(db.get_project(self.project["id"]))
        self.assertFalse(self.project_dir.exists())

    def test_second_delete_is_reported_as_gone(self) -> None:
        self.client.delete(self._url())
        again = self.client.delete(self._url())

        self.assertEqual(again.status_code, 404)
        # 文案要明确「已删除」，前端据此把它当成成功，而不是「接口不存在」
        self.assertIn("已删除", again.json()["detail"])


if __name__ == "__main__":
    unittest.main()
