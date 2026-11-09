from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import deconstruct
from app.agent.approvals import GATED_TOOLS, describe
from app.sandbox import PathRule, SandboxSettings
from app.text import save_text
from tests.test_deconstruct import SOURCE, FakeModel


class DeconstructPermissionsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.parent = Path(temp.name)
        self.root = self.parent / "project"
        self.root.mkdir()
        self.source = self.root / "source.txt"
        save_text(self.source, SOURCE)
        save_text(self.root / "book.json", "{}")

    def test_denied_source_and_agent_external_source_never_call_model(self):
        denied = self.root / ".env.txt"
        outside = self.parent / "outside.txt"
        save_text(denied, SOURCE)
        save_text(outside, SOURCE)
        with patch.object(deconstruct, "build_chat_model") as model:
            for file in (denied, outside):
                with self.subTest(file=file), self.assertRaises(deconstruct.DeconstructError):
                    deconstruct.run(self.root, file)
            model.assert_not_called()

    def test_ui_selected_external_source_is_allowed_but_secrets_still_denied(self):
        outside = self.parent / "outside.txt"
        secret = self.parent / "secrets" / "source.txt"
        save_text(outside, SOURCE)
        save_text(secret, SOURCE)
        with patch.object(deconstruct, "build_chat_model", return_value=FakeModel()):
            self.assertEqual(
                deconstruct.run(self.root, outside, allow_external=True, max_groups=1)["groups"], 1
            )
            with self.assertRaises(deconstruct.DeconstructError):
                deconstruct.run(self.root, secret, allow_external=True)

    def test_compound_writes_obey_denied_knowledge_timeline_expert_and_skill_paths(self):
        for pattern in ("kb/characters/**", "kb/outline/**", "experts/**", "skills/**"):
            with (
                self.subTest(pattern=pattern),
                tempfile.TemporaryDirectory(dir=self.parent) as temp,
            ):
                root = Path(temp)
                source = root / "source.txt"
                save_text(source, SOURCE)
                sandbox = SandboxSettings(rules=[PathRule(pattern=pattern, write="deny")])
                with patch.object(deconstruct, "build_chat_model", return_value=FakeModel()):
                    with self.assertRaises(PermissionError):
                        deconstruct.run(
                            root, source, sandbox=sandbox, create_expert=True, max_groups=1
                        )
                self.assertEqual(list(root.glob(pattern.replace("/**", "/**/*"))), [])

    def test_compound_tool_is_gated_with_clear_write_description(self):
        self.assertIn("deconstruct_source", GATED_TOOLS)
        _, _, note = describe(
            self.root,
            "deconstruct_source",
            {"path": "source.txt", "groups": 2, "create_expert": True},
        )
        self.assertIn("2", note)
        self.assertIn("知识库", note)
        self.assertIn("专家", note)
