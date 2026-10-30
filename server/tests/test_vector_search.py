from __future__ import annotations

import math
import shutil
import tempfile
import unittest
from pathlib import Path

from app.config import EmbeddingSettings
from app.kb.repository import save_entity
from app.kb.search import KbIndex


class FakeEmbedder:
    """不下载模型：按字符分布造向量，只用来验证 vec0 链路本身。"""

    provider = "local"

    def __init__(self, dim: int = 6):
        self.dim = dim
        self.name = f"fake-{dim}"

    def encode(self, texts):
        vectors = []
        for text in texts:
            vector = [0.0] * self.dim
            for index, char in enumerate(text):
                vector[index % self.dim] += 1.0 + (ord(char) % 7) / 10
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors


class VectorSearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="kb-vec-"))
        chapters = self.project / "chapters"
        chapters.mkdir(parents=True)
        (chapters / "0002-第二章.md").write_text(
            "第二章 夜谈\n\n林昭在落霞城的客栈里，听苏晴讲起旧事。", encoding="utf-8"
        )
        (chapters / "0009-第九章.md").write_text(
            "第九章 决裂\n\n林昭与师门决裂，独自下了青云山。", encoding="utf-8"
        )
        save_entity(self.project, "characters", "lin", {"name": "林昭"}, "青云山弟子，剑修。")
        self.index = KbIndex(
            self.project,
            EmbeddingSettings(provider="local", local_model="fake"),
        )
        # 跳过真实模型加载：直接注入假嵌入器
        self.index._embedder = FakeEmbedder()
        self.index._embedder_ready = True

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_rebuild_writes_vectors(self) -> None:
        result = self.index.rebuild()
        stats = self.index.stats()

        self.assertEqual(result["chunks"], stats["chunks"])
        self.assertEqual(stats["embedded"], stats["chunks"])
        self.assertEqual(stats["dim"], 6)
        self.assertEqual(stats["backend"], "sqlite-vec")

    def test_vector_mode_finds_chunk(self) -> None:
        self.index.rebuild()
        hits = self.index.search("青云山", mode="vector", top_k=3)

        self.assertTrue(hits)
        self.assertTrue(any("青云山" in hit["text"] for hit in hits))
        self.assertIn("vector_score", hits[0])

    def test_vector_mode_respects_kind_filter(self) -> None:
        self.index.rebuild()
        hits = self.index.search("林昭", mode="vector", kinds=["characters"], top_k=5)

        self.assertTrue(hits)
        self.assertTrue(all(hit["kind"] == "characters" for hit in hits))

    def test_vector_mode_respects_chapter_limit(self) -> None:
        self.index.rebuild()
        hits = self.index.search("林昭", mode="vector", chapter_limit=2, top_k=10)

        self.assertTrue(hits)
        self.assertTrue(all(hit["chapter"] <= 2 for hit in hits))

    def test_dimension_change_rebuilds_vec_table(self) -> None:
        self.index.rebuild()
        self.index._embedder = FakeEmbedder(dim=8)

        result = self.index.rebuild()
        stats = self.index.stats()

        self.assertEqual(stats["dim"], 8)
        self.assertEqual(result["embedded"], stats["chunks"])

    def test_incremental_write_updates_vector(self) -> None:
        self.index.rebuild()
        before = self.index.stats()["embedded"]

        save_entity(self.project, "characters", "su", {"name": "苏晴"}, "落霞城医女。")
        self.index.reindex_entity("characters", "su")

        self.assertEqual(self.index.stats()["embedded"], before + 1)
        hits = self.index.search("苏晴", mode="vector", kinds=["characters"], top_k=3)
        self.assertTrue(any(hit["title"] == "苏晴" for hit in hits))


if __name__ == "__main__":
    unittest.main()
