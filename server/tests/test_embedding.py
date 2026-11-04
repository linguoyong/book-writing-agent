from __future__ import annotations

import unittest
from unittest import mock

from app.config import EmbeddingSettings
from app.kb import embedding
from app.kb.embedding import (
    DEFAULT_LOCAL_MODEL,
    LOCAL_MODELS,
    EmbeddingError,
    build_embedder,
    probe,
    try_build_embedder,
)


class EmbeddingConfigTest(unittest.TestCase):
    """只测「选哪个嵌入器 / 配置错在哪」，不下载模型。"""

    def setUp(self) -> None:
        # 模型缓存是模块级全局：每个用例从空缓存开始，
        # 否则 mock 出来的 LocalEmbedder 会被缓存住、漏给后面的检索测试
        self._cache = mock.patch.object(embedding, "_MODEL_CACHE", {})
        self._cache.start()

    def tearDown(self) -> None:
        self._cache.stop()

    def test_model_table_has_expected_dims(self) -> None:
        self.assertEqual(LOCAL_MODELS[DEFAULT_LOCAL_MODEL]["dim"], 512)
        self.assertEqual(LOCAL_MODELS["jinaai/jina-embeddings-v2-base-zh"]["dim"], 768)

    def test_none_provider_returns_none(self) -> None:
        self.assertIsNone(build_embedder(EmbeddingSettings(provider="none")))

    def test_unknown_local_model_falls_back_to_default(self) -> None:
        fake = mock.Mock()
        with mock.patch.object(embedding, "LocalEmbedder", return_value=fake) as factory:
            embedder = build_embedder(
                EmbeddingSettings(provider="local", local_model="someone/unknown-model")
            )

        self.assertIs(embedder, fake)
        factory.assert_called_once_with(DEFAULT_LOCAL_MODEL)

    def test_local_embedder_is_cached_per_model(self) -> None:
        cfg = EmbeddingSettings(provider="local", local_model=DEFAULT_LOCAL_MODEL)
        with mock.patch.object(embedding, "LocalEmbedder", side_effect=[mock.Mock(), mock.Mock()]):
            first = build_embedder(cfg)
            second = build_embedder(cfg)

        self.assertIs(first, second)

    def test_openai_without_endpoint_raises(self) -> None:
        with self.assertRaises(EmbeddingError):
            build_embedder(EmbeddingSettings(provider="openai", base_url="", model=""))

    def test_unknown_provider_raises(self) -> None:
        with self.assertRaises(EmbeddingError):
            build_embedder(EmbeddingSettings(provider="nope"))

    def test_try_build_swallows_error(self) -> None:
        embedder, error = try_build_embedder(EmbeddingSettings(provider="openai", base_url=""))

        self.assertIsNone(embedder)
        self.assertIn("为空", error)

    def test_probe_reports_disabled(self) -> None:
        result = probe(EmbeddingSettings(provider="none"))

        self.assertFalse(result["ok"])
        self.assertIn("关闭", result["error"])
        self.assertEqual(result["dim"], 0)


class ApiEmbedderTest(unittest.TestCase):
    def test_encode_posts_and_returns_vectors(self) -> None:
        embedder = embedding.ApiEmbedder("http://127.0.0.1:9/v1", "k", "bge-m3")

        response = mock.Mock()
        response.json.return_value = {
            "data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]
        }
        client = mock.MagicMock()
        client.post.return_value = response
        client.__enter__.return_value = client
        client.__exit__.return_value = False

        with mock.patch.object(embedding.httpx, "Client", return_value=client):
            vectors = embedder.encode(["一", "二"])

        self.assertEqual(vectors, [[0.1, 0.2], [0.3, 0.4]])
        self.assertEqual(embedder.dim, 2)
        body = client.post.call_args.kwargs["json"]
        self.assertEqual(body["model"], "bge-m3")
        self.assertEqual(body["input"], ["一", "二"])

    def test_encode_error_becomes_embedding_error(self) -> None:
        embedder = embedding.ApiEmbedder("http://127.0.0.1:9/v1", "", "bge-m3")
        client = mock.MagicMock()
        client.post.side_effect = embedding.httpx.ConnectError("boom")
        client.__enter__.return_value = client
        client.__exit__.return_value = False

        with mock.patch.object(embedding.httpx, "Client", return_value=client):
            with self.assertRaises(EmbeddingError):
                embedder.encode(["一"])

    def test_empty_input_short_circuits(self) -> None:
        embedder = embedding.ApiEmbedder("http://127.0.0.1:9/v1", "", "bge-m3")

        self.assertEqual(embedder.encode([]), [])


if __name__ == "__main__":
    unittest.main()
