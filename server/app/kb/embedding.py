from __future__ import annotations

import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import EmbeddingSettings

# 本地可选的嵌入模型。维度写死在这里：vec0 表的维度建表时固定，
# 换模型必须重建索引，界面上要能提前说清楚。
LOCAL_MODELS: dict[str, dict[str, Any]] = {
    "BAAI/bge-small-zh-v1.5": {
        "dim": 512,
        "size_mb": 91,
        "label": "bge-small-zh · 快",
        "note": "默认档。中文短查询够用，5000 个切片约半分钟建完。",
    },
    "jinaai/jina-embeddings-v2-base-zh": {
        "dim": 768,
        "size_mb": 640,
        "label": "jina-v2-base-zh · 更准",
        "note": "中文长文本更强，首次下载 640MB，CPU 编码约慢 3–5 倍。",
    },
}
DEFAULT_LOCAL_MODEL = "BAAI/bge-small-zh-v1.5"

# 首次下载走镜像：huggingface.co 在多数国内网络下不可达。
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


class EmbeddingError(RuntimeError):
    """嵌入不可用（模型下载失败、接口报错、维度不符）。"""


@dataclass
class Embedder:
    provider: str
    name: str
    dim: int

    def encode(self, texts: Sequence[str]) -> list[list[float]]:  # pragma: no cover - 抽象
        raise NotImplementedError


class LocalEmbedder(Embedder):
    def __init__(self, model_name: str):
        meta = LOCAL_MODELS.get(model_name) or {}
        super().__init__(provider="local", name=model_name, dim=int(meta.get("dim") or 0))
        self._model_name = model_name
        self._model: Any = None
        self._lock = threading.Lock()

    def _ensure(self) -> Any:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from fastembed import TextEmbedding
            except ImportError as exc:  # pragma: no cover - 依赖缺失
                raise EmbeddingError(f"本地嵌入依赖缺失：{exc}") from exc
            try:
                model = TextEmbedding(model_name=self._model_name)
            except Exception as exc:  # noqa: BLE001 - 下载/加载失败都要给出可读提示
                raise EmbeddingError(f"本地模型加载失败：{type(exc).__name__}: {exc}") from exc
            if not self.dim:
                dim = len(next(iter(model.embed(["维度探测"]))))
                self.dim = dim
            self._model = model
        return self._model

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure()
        vectors = [list(map(float, item)) for item in model.embed(list(texts))]
        if vectors:
            # 以模型实际输出为准：配置里的维度只当提示，不参与校验
            self.dim = len(vectors[0])
        return vectors


class ApiEmbedder(Embedder):
    def __init__(self, base_url: str, api_key: str, model: str, dim: int = 0):
        super().__init__(provider="openai", name=model, dim=int(dim or 0))
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            with httpx.Client(timeout=120) as client:
                response = client.post(
                    f"{self.base_url}/embeddings",
                    headers=self._headers(),
                    json={"model": self.name, "input": list(texts)},
                )
                response.raise_for_status()
                data = response.json()["data"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise EmbeddingError(f"Embedding 接口调用失败：{type(exc).__name__}: {exc}") from exc
        vectors = [list(map(float, item["embedding"])) for item in data]
        if vectors:
            self.dim = len(vectors[0])
        return vectors


_MODEL_CACHE: dict[str, LocalEmbedder] = {}
_CACHE_LOCK = threading.Lock()


def build_embedder(cfg: EmbeddingSettings) -> Embedder | None:
    """按配置造一个嵌入器；provider=none 时返回 None（只用关键词检索）。"""
    provider = (cfg.provider or "none").lower()
    if provider == "none":
        return None
    if provider == "local":
        name = cfg.local_model or DEFAULT_LOCAL_MODEL
        if name not in LOCAL_MODELS:
            name = DEFAULT_LOCAL_MODEL
        with _CACHE_LOCK:
            embedder = _MODEL_CACHE.get(name)
            if embedder is None:
                embedder = LocalEmbedder(name)
                _MODEL_CACHE[name] = embedder
        return embedder
    if provider == "openai":
        if not cfg.base_url or not cfg.model:
            raise EmbeddingError("Embedding 接口地址或模型名为空")
        return ApiEmbedder(cfg.base_url, cfg.api_key, cfg.model, cfg.dimensions)
    raise EmbeddingError(f"未知的向量服务：{cfg.provider}")


def try_build_embedder(cfg: EmbeddingSettings) -> tuple[Embedder | None, str]:
    """检索路径用：失败不抛异常，返回错误文案让上层降级到关键词检索。"""
    try:
        return build_embedder(cfg), ""
    except EmbeddingError as exc:
        return None, str(exc)


def probe(cfg: EmbeddingSettings) -> dict[str, Any]:
    """设置页「测试」：真跑一次编码，返回维度与耗时。"""
    embedder = build_embedder(cfg)
    if embedder is None:
        return {"ok": False, "error": "向量服务已关闭", "dim": 0, "ms": 0}
    started = time.monotonic()
    try:
        vectors = embedder.encode(["林昭在青云山筑基，与师门决裂。", "宗门大比的规则是什么？"])
    except EmbeddingError as exc:
        return {"ok": False, "error": str(exc), "dim": 0, "ms": 0}
    elapsed = int((time.monotonic() - started) * 1000)
    dim = len(vectors[0]) if vectors else 0
    return {"ok": bool(dim), "error": "" if dim else "接口没有返回向量", "dim": dim, "ms": elapsed}
