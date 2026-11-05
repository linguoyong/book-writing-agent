from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import memory, prompts


class PromptLayerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp(prefix="prompts-"))
        self.project = self.home / "book"
        self.project.mkdir()
        patches = [
            mock.patch.object(prompts, "PROMPTS_DIR", self.home / "prompts"),
            mock.patch.object(memory, "MEMORY_DIR", self.home / "memory"),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self.home, ignore_errors=True)

    def test_identity_override_and_reset(self) -> None:
        default = prompts.read_layer("identity")
        self.assertTrue(default.strip())

        prompts.write_layer("identity", "自定义内核")
        self.assertEqual(prompts.read_layer("identity"), "自定义内核")

        prompts.reset_layer("identity")
        self.assertEqual(prompts.read_layer("identity"), default)

    def test_memory_layers_cannot_be_reset(self) -> None:
        prompts.write_layer("user", "# 我的偏好\n- 少用成语")
        self.assertEqual(prompts.read_layer("user"), "# 我的偏好\n- 少用成语")

        with self.assertRaises(prompts.PromptError):
            prompts.reset_layer("user")

    def test_project_layers_need_a_project(self) -> None:
        with self.assertRaises(prompts.PromptError):
            prompts.read_layer("domain")
        with self.assertRaises(prompts.PromptError):
            prompts.read_layer("project")

        content = prompts.read_layer("project", self.project)
        self.assertIn("AGENTS", content.upper())

    def test_domain_override_lives_in_project(self) -> None:
        prompts.write_layer("domain", "只写硬科幻", self.project)

        self.assertEqual(prompts.read_layer("domain", self.project), "只写硬科幻")
        self.assertTrue((self.project / "prompts" / "domain.md").exists())
        # 别的项目不受影响
        other = self.home / "other"
        other.mkdir()
        self.assertNotEqual(prompts.read_layer("domain", other), "只写硬科幻")

    def test_describe_marks_customized(self) -> None:
        rows = {item["layer"]: item for item in prompts.describe(self.project)}
        self.assertEqual(rows["identity"]["customized"], False)

        prompts.write_layer("identity", "改了")
        rows = {item["layer"]: item for item in prompts.describe(self.project)}
        self.assertEqual(rows["identity"]["customized"], True)
        self.assertGreater(rows["identity"]["limit"], 0)

    def test_describe_without_project_skips_project_layers(self) -> None:
        layers = [item["layer"] for item in prompts.describe()]

        self.assertIn("identity", layers)
        self.assertNotIn("domain", layers)


if __name__ == "__main__":
    unittest.main()
