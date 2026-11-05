from __future__ import annotations

import unittest

from app.main import app

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


class RouteSchemaTest(unittest.TestCase):
    """接口表的结构守卫：拆文件 / 改名时漏掉一条，这里会先红。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = app.openapi()
        cls.paths = cls.schema["paths"]

    def _operations(self) -> dict[str, set[str]]:
        return {
            path: {method for method in item if method in HTTP_METHODS}
            for path, item in self.paths.items()
        }

    def test_route_count_is_stable(self) -> None:
        # 数量掉了通常意味着某个 router 忘了 include
        self.assertEqual(len(self.paths), 82)
        self.assertEqual(sum(len(item) for item in self._operations().values()), 96)

    def test_key_endpoints_exist(self) -> None:
        expected = {
            "/api/health": {"get"},
            "/api/projects": {"get", "post"},
            "/api/projects/{project_id}": {"get", "delete"},
            "/api/projects/{project_id}/reindex": {"post"},
            "/api/projects/{project_id}/index/status": {"get"},
            "/api/projects/{project_id}/kb/{kind}": {"get", "post"},
            "/api/projects/{project_id}/tree": {"get"},
            "/api/projects/{project_id}/file": {"get", "put"},
            "/api/projects/{project_id}/git/diff": {"get"},
            "/api/sandbox/check": {"post"},
            "/api/chat": {"post"},
        }
        operations = self._operations()
        for path, methods in expected.items():
            with self.subTest(path=path):
                self.assertIn(path, operations)
                self.assertEqual(operations[path], methods)

    def test_reindex_accepts_full_flag(self) -> None:
        params = self.paths["/api/projects/{project_id}/reindex"]["post"].get("parameters", [])

        full = next((item for item in params if item["name"] == "full"), None)
        self.assertIsNotNone(full)
        self.assertFalse(full["required"])

    def test_every_operation_has_unique_id(self) -> None:
        operation_ids = [
            item[method]["operationId"]
            for item in self.paths.values()
            for method in item
            if method in HTTP_METHODS
        ]

        self.assertEqual(len(operation_ids), len(set(operation_ids)))

    def test_every_operation_documents_summary(self) -> None:
        # 中文摘要既是给人看的，也是 OpenAPI 里唯一的人类可读描述
        missing = [
            f"{path} {method}"
            for path, item in self.paths.items()
            for method in item
            if method in HTTP_METHODS and not item[method].get("summary")
        ]

        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
