from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.kb.repository import get_entity, parse_note, save_entity
from app.text import normalize_newlines, read_text, save_text


class NewlineTest(unittest.TestCase):
    """Windows 上「读—改—写」不能把 CRLF 再翻一层。"""

    def test_normalize_newlines(self) -> None:
        self.assertEqual(normalize_newlines("a\r\nb\rc\n"), "a\nb\nc\n")

    def test_read_text_returns_lf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.md"
            path.write_bytes("第一行\r\n第二行\r\n".encode("utf-8"))
            self.assertEqual(read_text(path), "第一行\n第二行\n")

    def test_save_text_collapses_existing_cr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.md"
            save_text(path, "第一行\r\n第二行\r\n")
            # 落盘只有一层 LF；再读一次也不该多出 \r
            self.assertEqual(path.read_bytes(), "第一行\n第二行\n".encode("utf-8"))
            save_text(path, read_text(path) + "第三行\n")
            self.assertEqual(path.read_bytes(), "第一行\n第二行\n第三行\n".encode("utf-8"))

    def test_save_text_keeps_original_when_content_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.md"
            save_text(path, "内容\n")
            for _ in range(3):
                save_text(path, read_text(path))
            self.assertEqual(path.read_bytes(), "内容\n".encode("utf-8"))

    def test_entity_round_trip_has_no_cr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for _ in range(3):
                save_entity(project, "characters", "linzhao", {"name": "林昭"}, "他走进屋子。\n\n门外有雨。")
            raw = (project / "kb" / "characters" / "linzhao.md").read_bytes()
            self.assertNotIn(b"\r", raw)
            self.assertEqual(get_entity(project, "characters", "linzhao")["body"], "他走进屋子。\n\n门外有雨。\n")


class FrontMatterTest(unittest.TestCase):
    def test_body_starting_with_rule_is_not_swallowed(self) -> None:
        source = "---\n他走进屋子，雨还没停。\n\n---\n\n门外忽然传来脚步声。\n"
        meta, body = parse_note(source)
        self.assertEqual(meta, {})
        self.assertIn("他走进屋子", body)
        self.assertIn("门外忽然传来脚步声", body)

    def test_normal_front_matter_still_parsed(self) -> None:
        meta, body = parse_note("---\nname: 林昭\nid: linzhao\n---\n\n正文\n")
        self.assertEqual(meta["name"], "林昭")
        self.assertEqual(body.strip(), "正文")


if __name__ == "__main__":
    unittest.main()
