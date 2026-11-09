from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent.backend import ProjectFilesystemBackend
from app.api.routes import common, files
from app.config import EmbeddingSettings, Settings
from app.kb.repository import dump_note, save_entity
from app.kb.search import KbIndex
from app.text import save_text


class FileIndexUpdatesTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.settings = Settings(embedding=EmbeddingSettings(provider="none"))
        patcher = patch("app.config.load_settings", return_value=self.settings)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.index = KbIndex(self.root, self.settings.embedding)

    def test_imported_and_written_chapters_have_distinct_ids_and_obey_chapter_limit(self) -> None:
        for source in ("chapters/0003.md", "manuscript/vol-01/ch-003.md"):
            save_text(
                self.root / source, dump_note({"chapter": 3, "title": "雨夜"}, "月光照亮铜镜。")
            )
        save_text(
            self.root / "manuscript/vol-02/ch-020.md", dump_note({"chapter": 20}, "月光照亮金镜。")
        )
        save_text(self.root / "manuscript/outline/plan.md", "月光照亮大纲。")
        save_text(self.root / "manuscript/_private.md", "月光照亮内部文件。")
        self.index.rebuild(embed=False)
        hits = self.index.search("月光", mode="keyword", chapter_limit=3)
        self.assertEqual(
            {item["source"] for item in hits}, {"chapters/0003.md", "manuscript/vol-01/ch-003.md"}
        )
        self.assertEqual(len({item["id"] for item in hits}), 2)
        with self.index.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 3)

    def test_editor_saves_update_card_and_chapter_search_without_rebuild(self) -> None:
        save_entity(self.root, "characters", "person", {"name": "甲"}, "旧卡片独有词。")
        save_text(
            self.root / "manuscript/vol-01/ch-003.md", dump_note({"chapter": 3}, "旧章节独有词。")
        )
        self.index.rebuild(embed=False)
        with (
            patch.object(files, "_require_project", return_value={"path": str(self.root)}),
            patch.object(common, "load_settings", return_value=self.settings),
        ):
            files.write_file(
                "test",
                common.WriteFileRequest(
                    path="kb/characters/person.md",
                    content=dump_note({"id": "person", "name": "甲"}, "新卡片标记。"),
                ),
            )
            files.write_file(
                "test",
                common.WriteFileRequest(
                    path="manuscript/vol-01/ch-003.md",
                    content=dump_note({"chapter": 3}, "新章节标记。"),
                ),
            )
        self.assertEqual(
            len(self.index.search("新卡片标记", kinds=["characters"], mode="keyword")), 1
        )
        self.assertEqual(
            len(self.index.search("新章节标记", kinds=["chapters"], mode="keyword")), 1
        )
        with self.index.connect() as conn:
            all_text = "\n".join(row[0] for row in conn.execute("SELECT text FROM chunks"))
        self.assertNotIn("旧卡片", all_text)
        self.assertNotIn("旧章节", all_text)

    def test_generic_edit_updates_index_and_snapshot(self) -> None:
        file = self.root / "manuscript/ch-003.md"
        save_text(file, dump_note({"chapter": 3}, "雨打铜镜。 oldmarker"))
        self.index.rebuild(embed=False)
        backend = ProjectFilesystemBackend(root_dir=str(self.root), virtual_mode=True)
        self.assertIsNone(backend.edit("/manuscript/ch-003.md", "oldmarker", "newmarker").error)
        hits = self.index.search("newmarker", mode="keyword")
        self.assertEqual(len(hits), 1)
        self.assertEqual(self.index.search("oldmarker", mode="keyword"), [])
        self.assertTrue(list((self.root / ".index/history").rglob("*.md")))

    def test_older_baseline_requires_a_text_refresh_after_upgrade(self) -> None:
        self.index.rebuild(embed=False)
        with self.index.connect() as conn:
            conn.execute("DELETE FROM index_meta WHERE key = 'sources_version'")
        self.assertFalse(self.index.has_baseline())

    def test_directory_rename_and_delete_refresh_manuscript_sources(self) -> None:
        file = self.root / "manuscript/vol-01/ch-003.md"
        save_text(file, dump_note({"chapter": 3}, "sourceword"))
        self.index.rebuild(embed=False)
        with (
            patch.object(files, "_require_project", return_value={"path": str(self.root)}),
            patch.object(common, "load_settings", return_value=self.settings),
        ):
            files.fs_rename(
                "test",
                common.FsRenameRequest(path="manuscript/vol-01", new_path="manuscript/vol-02"),
            )
            hits = self.index.search("sourceword", mode="keyword")
            self.assertEqual([hit["source"] for hit in hits], ["manuscript/vol-02/ch-003.md"])
            self.assertEqual(hits[0]["ref"], "manuscript/vol-02/ch-003.md")
            files.fs_delete("test", "manuscript/vol-02")
        self.assertEqual(self.index.search("sourceword", mode="keyword"), [])

    def test_background_encoding_does_not_reinsert_vectors_for_changed_or_deleted_text(
        self,
    ) -> None:
        from tests.test_vector_search import FakeEmbedder

        for deleted in (False, True):
            with self.subTest(deleted=deleted):
                file = self.root / "manuscript/ch-003.md"
                save_text(file, dump_note({"chapter": 3}, "oldmarker"))
                self.index.rebuild(embed=False, full=True)
                backend = ProjectFilesystemBackend(root_dir=str(self.root), virtual_mode=True)

                class EditingEmbedder(FakeEmbedder):
                    def encode(inner, texts, *, deleted=deleted, backend=backend):
                        if deleted:
                            self.assertIsNone(backend.delete("/manuscript/ch-003.md").error)
                        else:
                            self.assertIsNone(
                                backend.edit(
                                    "/manuscript/ch-003.md", "oldmarker", "newmarker"
                                ).error
                            )
                        return super().encode(texts)

                self.index._embedder = EditingEmbedder()
                self.index._embedder_ready = True
                self.index.embed_pending()
                with self.index.connect() as conn:
                    orphan = conn.execute(
                        "SELECT COUNT(*) FROM vec_chunks WHERE chunk_id NOT IN (SELECT id FROM chunks)"
                    ).fetchone()[0]
                self.assertEqual(orphan, 0)
                if not deleted:
                    self.index._embedder = FakeEmbedder()
                    self.index.embed_pending()
                    self.assertEqual(self.index.stats()["embedded"], self.index.stats()["chunks"])
