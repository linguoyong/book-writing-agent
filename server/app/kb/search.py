from __future__ import annotations

import json
import math
import re
import sqlite3
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import httpx
import jieba

from ..config import EmbeddingSettings
from .repository import KINDS, parse_note

INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    ref TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    chapter INTEGER NOT NULL DEFAULT 0,
    entities TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    content,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS vectors (
    chunk_id TEXT PRIMARY KEY,
    dim INTEGER NOT NULL,
    data BLOB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_kind ON chunks(kind);
CREATE INDEX IF NOT EXISTS idx_chunks_chapter ON chunks(chapter);
"""

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?…])\s*")


@dataclass
class Chunk:
    id: str
    kind: str
    ref: str
    title: str
    text: str
    chapter: int = 0
    entities: list[str] = field(default_factory=list)
    source: str = ""


def tokenize(text: str) -> list[str]:
    tokens = [t.strip() for t in jieba.cut_for_search(text) if t.strip()]
    return [t for t in tokens if _TOKEN_RE.fullmatch(t)]


def _fts_query(query: str) -> str:
    tokens = tokenize(query)
    if not tokens:
        tokens = [t for t in [_TOKEN_RE.sub("", query)] if t]
    unique = list(dict.fromkeys(tokens))
    return " OR ".join(f'"{t}"' for t in unique[:24])


class KbIndex:
    def __init__(self, project: Path, embedding: EmbeddingSettings | None = None):
        self.project = project
        self.index_dir = project / ".index"
        self.db_path = self.index_dir / "search.db"
        self.embedding = embedding or EmbeddingSettings()

    # ------------------------------------------------------------ 基础

    def connect(self) -> sqlite3.Connection:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.executescript(INDEX_SCHEMA)
        return conn

    def rebuild(self) -> dict[str, int]:
        chunks = list(self._collect_chunks())
        with self.connect() as conn:
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM chunks_fts")
            conn.execute("DELETE FROM vectors")
            for chunk in chunks:
                conn.execute(
                    "INSERT INTO chunks (id, kind, ref, title, text, chapter, entities, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        chunk.id,
                        chunk.kind,
                        chunk.ref,
                        chunk.title,
                        chunk.text,
                        chunk.chapter,
                        json.dumps(chunk.entities, ensure_ascii=False),
                        chunk.source,
                    ),
                )
                conn.execute(
                    "INSERT INTO chunks_fts (chunk_id, content) VALUES (?, ?)",
                    (chunk.id, " ".join(tokenize(f"{chunk.title} {chunk.text}"))),
                )
            conn.commit()

        embedded = 0
        if self.embedding.provider != "none" and chunks:
            embedded = self._embed_chunks(chunks)
        return {"chunks": len(chunks), "embedded": embedded}

    # ------------------------------------------------------------ 收集

    def _collect_chunks(self) -> Iterable[Chunk]:
        for kind in KINDS:
            directory = self.project / "kb" / kind
            if not directory.exists():
                continue
            for file in sorted(directory.glob("*.md")):
                meta, body = parse_note(file.read_text(encoding="utf-8"))
                entity_id = meta.get("id") or file.stem
                title = meta.get("name") or meta.get("title") or file.stem
                text = f"{title}\n{body}".strip()
                if not text:
                    continue
                yield Chunk(
                    id=f"{kind}:{entity_id}",
                    kind=kind,
                    ref=entity_id,
                    title=str(title),
                    text=text,
                    chapter=int(meta.get("first_chapter") or 0),
                    entities=[str(entity_id)],
                    source=str(file.relative_to(self.project)),
                )

        chapters_dir = self.project / "chapters"
        if chapters_dir.exists():
            for file in sorted(chapters_dir.glob("*.md")):
                meta, body = parse_note(file.read_text(encoding="utf-8"))
                chapter_no = _chapter_number(meta, file.stem)
                title = meta.get("title") or file.stem
                for index, piece in enumerate(_split_text(body)):
                    yield Chunk(
                        id=f"chapter:{chapter_no}:{index}",
                        kind="chapters",
                        ref=str(chapter_no),
                        title=f"第{chapter_no}章 {title}",
                        text=piece,
                        chapter=chapter_no,
                        entities=[],
                        source=str(file.relative_to(self.project)),
                    )

    # ------------------------------------------------------------ 向量

    def _embed_chunks(self, chunks: list[Chunk]) -> int:
        cfg = self.embedding
        if not cfg.base_url or not cfg.model:
            return 0
        headers = {"Content-Type": "application/json"}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"

        written = 0
        batch_size = 16
        with httpx.Client(timeout=120) as client:
            with self.connect() as conn:
                for start in range(0, len(chunks), batch_size):
                    batch = chunks[start : start + batch_size]
                    payload = {
                        "model": cfg.model,
                        "input": [f"{c.title}\n{c.text}" for c in batch],
                    }
                    response = client.post(
                        f"{cfg.base_url.rstrip('/')}/embeddings",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()["data"]
                    for chunk, item in zip(batch, data):
                        vector = item["embedding"]
                        blob = struct.pack(f"<{len(vector)}f", *vector)
                        conn.execute(
                            "INSERT OR REPLACE INTO vectors (chunk_id, dim, data) VALUES (?, ?, ?)",
                            (chunk.id, len(vector), blob),
                        )
                        written += 1
                conn.commit()
        return written

    def _query_vector(self, query: str) -> list[float] | None:
        cfg = self.embedding
        if cfg.provider == "none" or not cfg.base_url:
            return None
        headers = {"Content-Type": "application/json"}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        try:
            with httpx.Client(timeout=60) as client:
                response = client.post(
                    f"{cfg.base_url.rstrip('/')}/embeddings",
                    headers=headers,
                    json={"model": cfg.model, "input": [query]},
                )
                response.raise_for_status()
                return response.json()["data"][0]["embedding"]
        except (httpx.HTTPError, KeyError, IndexError):
            return None

    # ------------------------------------------------------------ 检索

    def search(
        self,
        query: str,
        kinds: list[str] | None = None,
        chapter_limit: int | None = None,
        top_k: int = 8,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []

        lexical = self._search_lexical(query, kinds, chapter_limit, top_k * 2)
        vector_hits = self._search_vector(query, kinds, chapter_limit, top_k * 2)

        fused: dict[str, dict[str, Any]] = {}
        for rank, item in enumerate(lexical):
            fused.setdefault(item["id"], {**item, "score": 0.0})["score"] += 1 / (60 + rank + 1)
        for rank, item in enumerate(vector_hits):
            entry = fused.setdefault(item["id"], {**item, "score": 0.0})
            entry["score"] += 1 / (60 + rank + 1)
            entry.setdefault("vector_score", item["vector_score"])

        results = sorted(fused.values(), key=lambda x: x["score"], reverse=True)[:top_k]
        return results

    def _search_lexical(
        self,
        query: str,
        kinds: list[str] | None,
        chapter_limit: int | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        match = _fts_query(query)
        if not match:
            return []

        sql = [
            "SELECT c.*, bm25(chunks_fts) AS rank",
            "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.chunk_id",
            "WHERE chunks_fts MATCH ?",
        ]
        params: list[Any] = [match]
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            sql.append(f"AND c.kind IN ({placeholders})")
            params.extend(kinds)
        if chapter_limit:
            sql.append("AND c.chapter <= ?")
            params.append(chapter_limit)
        sql.append("ORDER BY rank LIMIT ?")
        params.append(limit)

        with self.connect() as conn:
            rows = conn.execute(" ".join(sql), params).fetchall()

        results = []
        for row in rows:
            results.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "ref": row["ref"],
                    "title": row["title"],
                    "text": row["text"],
                    "chapter": row["chapter"],
                    "entities": json.loads(row["entities"] or "[]"),
                    "source": row["source"],
                    "lexical_score": float(-row["rank"]),
                }
            )
        return results

    def _search_vector(
        self,
        query: str,
        kinds: list[str] | None,
        chapter_limit: int | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        query_vector = self._query_vector(query)
        if not query_vector:
            return []

        sql = [
            "SELECT c.*, v.data, v.dim FROM vectors v JOIN chunks c ON c.id = v.chunk_id WHERE 1=1"
        ]
        params: list[Any] = []
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            sql.append(f"AND c.kind IN ({placeholders})")
            params.extend(kinds)
        if chapter_limit:
            sql.append("AND c.chapter <= ?")
            params.append(chapter_limit)

        with self.connect() as conn:
            rows = conn.execute(" ".join(sql), params).fetchall()

        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            vector = struct.unpack(f"<{row['dim']}f", row["data"])
            scored.append((_cosine(query_vector, vector), row))
        scored.sort(key=lambda pair: pair[0], reverse=True)

        results = []
        for score, row in scored[:limit]:
            results.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "ref": row["ref"],
                    "title": row["title"],
                    "text": row["text"],
                    "chapter": row["chapter"],
                    "entities": json.loads(row["entities"] or "[]"),
                    "source": row["source"],
                    "vector_score": score,
                }
            )
        return results

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
            embedded = conn.execute("SELECT COUNT(*) AS n FROM vectors").fetchone()["n"]
        return {"chunks": total, "embedded": embedded, "provider": self.embedding.provider}


def _cosine(a: list[float], b: Iterable[float]) -> float:
    b_list = list(b)
    if len(a) != len(b_list):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b_list))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b_list))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _split_text(text: str, max_len: int = 600, overlap: int = 80) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paragraphs:
        return []
    pieces: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_len:
            for sentence in _SENTENCE_SPLIT.split(paragraph):
                if not sentence:
                    continue
                if len(buffer) + len(sentence) <= max_len:
                    buffer += sentence
                else:
                    if buffer:
                        pieces.append(buffer)
                    buffer = sentence
            continue
        if len(buffer) + len(paragraph) <= max_len:
            buffer = f"{buffer}\n{paragraph}".strip()
        else:
            if buffer:
                pieces.append(buffer)
            tail = buffer[-overlap:] if overlap and buffer else ""
            buffer = f"{tail}\n{paragraph}".strip()
    if buffer:
        pieces.append(buffer)
    return pieces


def _chapter_number(meta: dict[str, Any], stem: str) -> int:
    for key in ("chapter", "index", "number"):
        value = meta.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    match = re.search(r"(\d+)", stem)
    return int(match.group(1)) if match else 0
