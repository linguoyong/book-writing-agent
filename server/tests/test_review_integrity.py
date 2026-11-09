from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import review, search_text
from app.agent.backend import ProjectFilesystemBackend
from app.api.routes import common, files
from app.config import EmbeddingSettings, Settings
from app.fileops import FileConflictError, write_project_text
from app.kb.repository import dump_note, parse_note
from app.text import read_text, save_text
from tests.test_review import BODY, FakeModel, payload


class ReviewIntegrityTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.file = self.root / "manuscript/vol-01/ch-003.md"
        save_text(self.file, dump_note({"title": "第3章 雨夜", "chapter": 3}, BODY))
        save_text(self.root / "book.json", '{"title":"test"}')
        settings = Settings(embedding=EmbeddingSettings(provider="none"))
        for target in ("app.config.load_settings", "app.api.routes.common.load_settings"):
            patcher = patch(target, return_value=settings)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_review(self, model: FakeModel | None = None):
        with patch.object(review, "build_chat_model", return_value=model or FakeModel(payload())):
            return review.run_review(self.root, "3")

    def assert_stale(self) -> None:
        self.assertEqual(review.chapter_status(self.root, "3"), "stale")
        self.assertEqual(review.load_review(self.root, "3")["status"], "stale")
        self.assertEqual(review.list_reviews(self.root)[0]["status"], "stale")

    def test_review_does_not_overwrite_edits_made_during_model_call(self) -> None:
        latest = dump_note({"title": "改后的标题", "chapter": 3}, BODY + "\n刚保存的新稿。")

        class EditingModel(FakeModel):
            def invoke(inner, prompt, **kwargs):
                write_project_text(self.root, self.file, latest)
                return super().invoke(prompt, **kwargs)

        result = self.run_review(EditingModel(payload()))
        self.assertEqual(result.status, "stale")
        self.assertEqual(read_text(self.file), latest)
        self.assertEqual(len(list((self.root / ".index/reviews/history").rglob("*.json"))), 1)
        self.assert_stale()

    def test_review_preserves_metadata_changes_with_identical_body(self) -> None:
        class MetadataModel(FakeModel):
            def invoke(inner, prompt, **kwargs):
                save_text(
                    self.file, dump_note({"title": "新标题", "chapter": 3, "note": "保留"}, BODY)
                )
                return super().invoke(prompt, **kwargs)

        self.assertEqual(self.run_review(MetadataModel(payload())).status, "pass")
        meta, _ = parse_note(read_text(self.file))
        self.assertEqual(meta["note"], "保留")
        self.assertEqual(meta["title"], "新标题")

    def test_review_does_not_recreate_deleted_chapter(self) -> None:
        class DeletingModel(FakeModel):
            def invoke(inner, prompt, **kwargs):
                self.file.unlink()
                return super().invoke(prompt, **kwargs)

        self.assertEqual(self.run_review(DeletingModel(payload())).status, "stale")
        self.assertFalse(self.file.exists())

    def test_editor_save_invalidates_review_and_checks_deleted_file_conflict(self) -> None:
        self.run_review()
        with patch.object(files, "_require_project", return_value={"path": str(self.root)}):
            files.write_file(
                "test",
                common.WriteFileRequest(
                    path="manuscript/vol-01/ch-003.md",
                    content=read_text(self.file) + "\n编辑器改稿。",
                ),
            )
        self.assert_stale()
        mtime = int(self.file.stat().st_mtime * 1000)
        self.file.unlink()
        with self.assertRaises(FileConflictError):
            write_project_text(self.root, self.file, BODY, expected_mtime=mtime)

    def test_search_replace_and_generic_file_tools_invalidate_review(self) -> None:
        for operation in ("replace", "write", "edit"):
            with self.subTest(operation=operation):
                self.run_review()
                backend = ProjectFilesystemBackend(root_dir=str(self.root), virtual_mode=True)
                if operation == "replace":
                    search_text.replace(self.root, "陆沉", "沈舟", dry_run=False)
                elif operation == "write":
                    self.assertIsNone(
                        backend.write("/manuscript/vol-01/ch-003.md", BODY + "\n写入新稿。").error
                    )
                else:
                    self.assertIsNone(
                        backend.edit("/manuscript/vol-01/ch-003.md", "院子里", "庭院里", True).error
                    )
                self.assert_stale()

    def test_old_editor_snapshot_cannot_restore_pass_status(self) -> None:
        self.run_review()
        snapshot = read_text(self.file)
        write_project_text(self.root, self.file, snapshot + "\n改稿。")
        # 编辑器仍持有旧的 pass front-matter，再保存相同正文也不能复活它。
        meta, _ = parse_note(snapshot)
        _, body = parse_note(read_text(self.file))
        write_project_text(self.root, self.file, dump_note(meta, body))
        self.assertEqual(parse_note(read_text(self.file))[0]["review"]["status"], "stale")
        self.assert_stale()

    def test_external_edit_and_legacy_review_are_reported_as_stale(self) -> None:
        self.run_review()
        save_text(self.file, read_text(self.file) + "\n外部编辑器改稿。")
        self.assert_stale()
        meta, body = parse_note(read_text(self.file))
        meta["review"].pop("body_hash")
        meta["review"]["status"] = "pass"
        save_text(self.file, dump_note(meta, body))
        self.assert_stale()

    def test_missing_or_invalid_scores_and_verdict_do_not_write_review(self) -> None:
        invalid = [
            payload(dimensions={"consistency": 5}),
            payload(verdict="maybe"),
            payload(issues={}),
        ]
        for value in (0, 6, True, "5", 3.5, None):
            scores = {key: 4 for key in review.DIMENSIONS}
            scores["voice"] = value
            invalid.append(payload(dimensions=scores))
        original = read_text(self.file)
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(review.ReviewError):
                self.run_review(FakeModel(data))
            self.assertEqual(read_text(self.file), original)

    def test_oversized_chapter_is_rejected_before_any_model_call(self) -> None:
        save_text(self.file, dump_note({"chapter": 3}, BODY + "甲" * review.MAX_CHAPTER_CHARS))
        original = read_text(self.file)
        with patch.object(review, "build_chat_model") as build:
            with self.assertRaisesRegex(review.ReviewError, "上限"):
                review.run_review(self.root, "3")
            build.assert_not_called()
        self.assertEqual(read_text(self.file), original)

    def test_longest_accepted_chapter_is_reviewed_to_the_end(self) -> None:
        body = "甲" * (review.MAX_CHAPTER_CHARS - 8) + "TAIL_END"
        save_text(self.file, dump_note({"chapter": 3}, body))
        model = FakeModel(payload())
        result = self.run_review(model)
        self.assertIn("TAIL_END", model.prompts[0])
        self.assertEqual(result.reviewed_chars, review.MAX_CHAPTER_CHARS)
        self.assertEqual(result.status, "pass")
        stored = json.loads(read_text(self.root / ".index/reviews/vol-01__ch-003.json"))
        self.assertEqual(stored["body_hash"], result.body_hash)
