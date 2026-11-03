from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app.config import EmbeddingSettings
from app.kb.search import KbIndex
from app.text import save_text


class CountingEmbedder:
    """只数调用量，不下载模型：增量重建的价值就在于少调几次。"""

    provider = "local"

    def __init__(self, dim: int = 4):
        self.dim = dim
        self.name = "counting"
        self.texts = 0
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        self.texts += len(texts)
        return [[1.0, 0.0, 0.0, 0.0][: self.dim] for _ in texts]


class IncrementalRebuildTest(unittest.TestCase):
    """改了哪一章就只重排哪一章，向量按切片内容复用。"""

    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="kb-inc-"))
        self.chapters = self.project / "chapters"
        self.chapters.mkdir(parents=True)
        for number in (1, 2, 3):
            self._write_chapter(number, f"第{number}章的正文。" * 40)
        self.index = KbIndex(self.project, EmbeddingSettings())
        self.index.rebuild(embed=False)

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def _write_chapter(self, number: int, body: str) -> None:
        save_text(
            self.chapters / f"{number:04d}-x.md",
            f"---\nchapter: {number}\ntitle: 第{number}章\n---\n\n{body}\n",
        )

    def _ids(self) -> list[str]:
        return [item["id"] for item in self.index.list_chunks(limit=200)["items"]]

    def test_second_rebuild_skips_unchanged_files(self) -> None:
        result = self.index.rebuild(embed=False)

        self.assertEqual(result["changed"], 0)
        self.assertEqual(result["skipped"], 3)
        self.assertEqual(result["removed"], 0)

    def test_edit_one_chapter_only_touches_that_file(self) -> None:
        before = self._ids()
        kept = [item for item in before if not item.startswith("chapter:2:")]

        self._write_chapter(2, "改过的第二章。" * 40)
        result = self.index.rebuild(embed=False)
        after = self._ids()

        self.assertEqual(result["changed"], 1)
        self.assertEqual(result["skipped"], 2)
        self.assertTrue(set(kept).issubset(set(after)))
        self.assertFalse(
            [item for item in after if item in before and item.startswith("chapter:2:")]
        )

    def test_editing_last_paragraph_keeps_other_chunk_ids(self) -> None:
        # 每段都超过 max_len，一段一片；改最后一段不该动到前面的切片
        paragraphs = [f"第{index}段。" + "情节推进。" * 60 for index in range(1, 5)]
        self._write_chapter(4, "\n\n".join(paragraphs))
        self.index.rebuild(embed=False)
        before = [item for item in self._ids() if item.startswith("chapter:4:")]
        self.assertEqual(len(before), 4)

        paragraphs[-1] = "第4段。整段改写。" * 20
        self._write_chapter(4, "\n\n".join(paragraphs))
        self.index.rebuild(embed=False)
        after = [item for item in self._ids() if item.startswith("chapter:4:")]

        self.assertEqual(len(after), 4)
        # 前三片正文没动，id 应当原样保留（末尾那片带重叠尾巴，会跟着变）
        self.assertEqual(len(set(before) & set(after)), 3)

    def test_deleted_file_drops_its_chunks(self) -> None:
        (self.chapters / "0002-x.md").unlink()

        result = self.index.rebuild(embed=False)

        self.assertEqual(result["removed"], 1)
        self.assertFalse([item for item in self._ids() if item.startswith("chapter:2:")])
        self.assertEqual(len(self.index.list_chunks(limit=200)["items"]), 2)

    def test_touch_without_content_change_is_skipped(self) -> None:
        file = self.chapters / "0001-x.md"
        text = file.read_text(encoding="utf-8")
        save_text(file, text)  # 内容一样，只有 mtime 变了

        result = self.index.rebuild(embed=False)

        self.assertEqual(result["changed"], 0)
        self.assertEqual(result["skipped"], 3)

    def test_text_only_rebuild_leaves_vectors_for_later(self) -> None:
        self._write_chapter(9, "新增的第九章。" * 30)

        self.index.rebuild(embed=False)
        self.assertEqual(self.index.stats()["embedded"], 0)

        # 只补文本后再补向量：应当只编码缺的那些，而不是重来一遍
        result = self.index.rebuild(embed=True)
        self.assertEqual(result["embedded"], self.index.stats()["chunks"])


class IncrementalEmbeddingTest(unittest.TestCase):
    """向量按 chunk id 复用：没改的切片不该重新编码。"""

    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="kb-inc-vec-"))
        chapters = self.project / "chapters"
        chapters.mkdir(parents=True)
        body = "\n\n".join(f"第{index}段。" + "情节推进。" * 60 for index in range(1, 5))
        (chapters / "0001-x.md").write_text(f"---\nchapter: 1\n---\n\n{body}\n", encoding="utf-8")
        self.index = KbIndex(self.project, EmbeddingSettings(provider="local", local_model="fake"))
        self.embedder = CountingEmbedder()
        self.index._embedder = self.embedder
        self.index._embedder_ready = True

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_only_changed_chunk_is_reembedded(self) -> None:
        first = self.index.rebuild()
        total = first["chunks"]
        self.assertEqual(self.embedder.texts, total)
        self.assertGreater(total, 1)

        file = self.project / "chapters" / "0001-x.md"
        text = file.read_text(encoding="utf-8")
        file.write_text(text.replace("第4段。", "第4段改写。"), encoding="utf-8")

        self.embedder.texts = 0
        result = self.index.rebuild()

        self.assertEqual(self.embedder.texts, 1)
        self.assertEqual(result["embedded"], 1)
        self.assertEqual(self.index.stats()["embedded"], total)

    def test_full_rebuild_reembeds_everything(self) -> None:
        total = self.index.rebuild()["chunks"]

        self.embedder.texts = 0
        result = self.index.rebuild(full=True)

        self.assertEqual(result["chunks"], total)
        self.assertEqual(self.embedder.texts, total)


if __name__ == "__main__":
    unittest.main()
