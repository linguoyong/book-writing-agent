from __future__ import annotations

import json
import re
import sqlite3
import struct
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import jieba

try:  # 可选依赖：没有 sqlite-vec 时自动退回关键词检索
    import sqlite_vec
except ImportError:  # pragma: no cover
    sqlite_vec = None

from ..config import EmbeddingSettings
from ..text import read_text
from .embedding import EmbeddingError, LOCAL_MODELS, try_build_embedder
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

CREATE TABLE IF NOT EXISTS index_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_kind ON chunks(kind);
CREATE INDEX IF NOT EXISTS idx_chunks_chapter ON chunks(chapter);
"""

_LEGACY_SCHEMA = """
DROP TABLE IF EXISTS vectors;
"""

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?…])\s*")
_ALIAS_SPLIT = re.compile(r"[,，、;；/|]")
_HEADING_NO = re.compile(r"^第\s*[0-9零一二三四五六七八九十百千万两]+\s*[章回节篇]")

# 实体名 → (kind, id) 的缓存。检索每次都要用，但目录扫描不该每次都做。
_ENTITY_CACHE: dict[str, tuple[float, dict[str, tuple[str, str]]]] = {}
_ENTITY_TTL = 15.0

# 单字实体名（晦、影、灯）按字符匹配；这些虚词永远不当实体名命中
_NAME_STOPWORDS = {
    "的", "了", "是", "在", "我", "你", "他", "她", "它", "不", "有", "和", "与",
    "就", "都", "也", "很", "又", "把", "被", "给", "让", "从", "向", "对", "为",
    "以", "及", "或", "而", "则", "若", "且", "这", "那", "哪", "谁", "什",
}

ProgressHook = Callable[[str, int, int], None]


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


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


class KbIndex:
    def __init__(self, project: Path, embedding: EmbeddingSettings | None = None):
        self.project = project
        self.index_dir = project / ".index"
        self.db_path = self.index_dir / "search.db"
        self.embedding = embedding or EmbeddingSettings()
        self._embedder: Any = None
        self._embedder_ready = False
        self.last_vector_error = ""

    # ------------------------------------------------------------ 基础

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """每次调用独立连接；`with` 退出时提交并关闭。

        注意 sqlite3.Connection 自带的上下文管理器只提交、不关闭，
        直接 `with sqlite3.connect(...)` 会泄漏文件句柄。
        """
        self.index_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            _load_sqlite_vec(conn)
            conn.executescript(INDEX_SCHEMA)
            conn.executescript(_LEGACY_SCHEMA)
            yield conn
            conn.commit()
        finally:
            conn.close()

    def embedder(self) -> Any:
        """惰性构造嵌入器：配置了本地模型时首次调用会加载模型（约几秒）。"""
        if self._embedder_ready:
            return self._embedder
        self._embedder_ready = True
        self._embedder, error = try_build_embedder(self.embedding)
        if error:
            self.last_vector_error = error
        return self._embedder

    def rebuild(
        self, progress: ProgressHook | None = None, embed: bool = True
    ) -> dict[str, int]:
        """重建切片索引。

        embed=False 只重建文本索引（关键词检索）：隐式触发（打开切片页、
        对话里首次检索）时不能把整个书稿的向量编码塞进请求里，向量交给
        知识库页的「重建索引」后台任务或导入流程补齐。
        """
        chunks = list(self._collect_chunks())
        with self.connect() as conn:
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM chunks_fts")
            for chunk in chunks:
                _insert_chunk(conn, chunk)
            self._mark_baseline(conn)
            conn.commit()

        embedded = 0
        if embed and chunks:
            embedded = self._embed_chunks(chunks, progress)
        elif progress:
            progress("done", 0, len(chunks))
        return {"chunks": len(chunks), "embedded": embedded}

    def has_baseline(self) -> bool:
        """是否做过一次全量重建。

        增量写入（reindex_entity）只补单条，必须先有全量基线，
        否则残留的旧索引会让「chunks > 0」误判为已建库。
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM index_meta WHERE key = 'baseline'"
            ).fetchone()
        return bool(row and row["value"] == "1")

    @staticmethod
    def _mark_baseline(conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES ('baseline', '1')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES ('built_at', ?)",
            (datetime.now(timezone.utc).isoformat(),),
        )

    # ------------------------------------------------------------ 收集

    def _collect_chunks(self) -> Iterable[Chunk]:
        for kind in KINDS:
            directory = self.project / "kb" / kind
            if not directory.exists():
                continue
            for file in sorted(directory.glob("*.md")):
                meta, body = parse_note(read_text(file))
                entity_id = meta.get("id") or file.stem
                title = meta.get("name") or meta.get("title") or file.stem
                pieces = _split_entity(str(title), body)
                if not pieces:
                    continue
                for index, piece in enumerate(pieces):
                    yield Chunk(
                        # 单切片沿用旧 id（增量写入按它定位），拆开后才带序号
                        id=f"{kind}:{entity_id}"
                        if len(pieces) == 1
                        else f"{kind}:{entity_id}:{index}",
                        kind=kind,
                        ref=entity_id,
                        title=str(title),
                        text=piece,
                        chapter=int(meta.get("first_chapter") or 0),
                        entities=[str(entity_id)],
                        source=str(file.relative_to(self.project)),
                    )

        chapters_dir = self.project / "chapters"
        if chapters_dir.exists():
            for file in sorted(chapters_dir.glob("*.md")):
                meta, body = parse_note(read_text(file))
                chapter_no = _chapter_number(meta, file.stem)
                title = str(meta.get("title") or file.stem)
                # 导入的章节标题本身就带「第005章」，别再重复加前缀
                label = title if _HEADING_NO.match(title) else f"第{chapter_no}章 {title}"
                for index, piece in enumerate(_split_text(body)):
                    yield Chunk(
                        id=f"chapter:{chapter_no}:{index}",
                        kind="chapters",
                        ref=str(chapter_no),
                        title=label,
                        text=piece,
                        chapter=chapter_no,
                        entities=[],
                        source=str(file.relative_to(self.project)),
                    )

    # ------------------------------------------------------------ 增量索引

    def reindex_entity(self, kind: str, entity_id: str) -> int:
        """只重建一个实体的切片，避免每次写入触发全库重扫。"""
        from .repository import entity_file, safe_entity_id

        if kind not in KINDS:
            return 0
        invalidate_entities(self.project)
        try:
            file = entity_file(self.project, kind, entity_id)
        except ValueError:
            return 0
        chunk_id = f"{kind}:{safe_entity_id(entity_id)}"
        if not self.has_baseline():
            # 还没有全量基线时先补一次：否则只索引这一条，
            # 已导入的章节与既有条目会被永久挡在检索之外。
            self.rebuild()
            return 1 if file.exists() else 0
        with self.connect() as conn:
            # 拆开后的切片是 kind:entity:0/1/2…，增量写入要把这一组一起换掉
            stale = conn.execute(
                "SELECT id FROM chunks WHERE id = ? OR id LIKE ?",
                (chunk_id, f"{chunk_id}:%"),
            ).fetchall()
            for row in stale:
                conn.execute("DELETE FROM chunks WHERE id = ?", (row["id"],))
                conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (row["id"],))
                _delete_vector(conn, row["id"])
            conn.commit()
            if not file.exists():
                return 0
            meta, body = parse_note(read_text(file))
            title = meta.get("name") or meta.get("title") or file.stem
            pieces = _split_entity(str(title), body)
            if not pieces:
                return 0
            chunks = [
                Chunk(
                    id=chunk_id if len(pieces) == 1 else f"{chunk_id}:{index}",
                    kind=kind,
                    ref=str(meta.get("id") or file.stem),
                    title=str(title),
                    text=piece,
                    chapter=int(meta.get("first_chapter") or 0),
                    entities=[str(entity_id)],
                    source=str(file.relative_to(self.project)),
                )
                for index, piece in enumerate(pieces)
            ]
            for chunk in chunks:
                _insert_chunk(conn, chunk)
            conn.commit()
        self._embed_chunks(chunks, None)
        return len(chunks)

    # ------------------------------------------------------------ 向量

    def _embed_chunks(self, chunks: list[Chunk], progress: ProgressHook | None) -> int:
        embedder = self.embedder()
        if embedder is None or not chunks:
            if progress:
                progress("done", 0, len(chunks))
            return 0

        # 本地模型批量大一点更划算（实测 64 条/批比 32 条快约 25%）
        batch_size = 64 if embedder.provider == "local" else 16
        total = len(chunks)
        written = 0
        # 整个编码过程共用一个连接：每批开连接 + 重新加载 vec 扩展很费时间
        with self.connect() as conn:
            started = 0
            while started < total:
                batch = chunks[started : started + batch_size]
                try:
                    vectors = embedder.encode([f"{c.title}\n{c.text}" for c in batch])
                except EmbeddingError as exc:
                    self.last_vector_error = str(exc)
                    if progress:
                        progress("error", written, total)
                    return written
                dim = embedder.dim or (len(vectors[0]) if vectors else 0)
                if not dim:
                    return written
                _ensure_vec_table(conn, dim, embedder.name, embedder.provider)
                for chunk, vector in zip(batch, vectors):
                    _delete_vector(conn, chunk.id)
                    conn.execute(
                        "INSERT INTO vec_chunks (chunk_id, kind, chapter, embedding) "
                        "VALUES (?, ?, ?, ?)",
                        (chunk.id, chunk.kind, chunk.chapter, _pack(vector)),
                    )
                    written += 1
                conn.commit()
                started += len(batch)
                if progress:
                    progress("embed", written, total)
        if progress:
            progress("done", written, total)
        return written

    def _query_vector(self, query: str) -> list[float] | None:
        embedder = self.embedder()
        if embedder is None:
            return None
        try:
            vectors = embedder.encode([query])
        except EmbeddingError as exc:
            self.last_vector_error = str(exc)
            return None
        return vectors[0] if vectors else None

    # ------------------------------------------------------------ 检索

    def _route_entities(
        self,
        items: list[dict[str, Any]],
        matched: set[tuple[str, str]],
        key: str,
        kinds: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """把查询里点名的实体顶到前面，并保证它至少有一条切片在结果里。

        只靠 BM25/向量时，一张密集的总纲能压过角色卡本身；
        既然用户已经点名了，就不该让它排第三。
        """
        if kinds:
            # 只在被请求的类型里路由，别把角色卡塞进「只搜大纲」的结果里
            matched = {tag for tag in matched if tag[0] in kinds}
        if not matched:
            return items
        max_value = max((float(item.get(key) or 0.0) for item in items), default=0.0)
        if max_value <= 0:
            max_value = 1.0
        # 略高于当前最高分：命名的实体排到最前，多条命中之间靠稳定排序保持原顺序
        floor = max_value * 1.05
        if key == "vector_score":
            floor = min(1.0, floor)

        seen: set[tuple[str, str]] = set()
        for item in items:
            tag = (str(item.get("kind")), str(item.get("ref")))
            if tag not in matched:
                continue
            seen.add(tag)
            if float(item.get(key) or 0.0) < floor:
                item[key] = floor
            item["routed"] = True

        missing = matched - seen
        if not missing:
            return items

        with self.connect() as conn:
            for kind, ref in missing:
                row = conn.execute(
                    "SELECT * FROM chunks WHERE kind = ? AND (id = ? OR id LIKE ?) "
                    "ORDER BY id LIMIT 1",
                    (kind, f"{kind}:{ref}", f"{kind}:{ref}:%"),
                ).fetchone()
                if row is None:
                    continue
                items.append(
                    {
                        "id": row["id"],
                        "kind": row["kind"],
                        "ref": row["ref"],
                        "title": row["title"],
                        "text": row["text"],
                        "chapter": row["chapter"],
                        "entities": json.loads(row["entities"] or "[]"),
                        "source": row["source"],
                        key: floor,
                        "routed": True,
                    }
                )
        return items

    def search(
        self,
        query: str,
        kinds: list[str] | None = None,
        chapter_limit: int | None = None,
        top_k: int = 8,
        threshold: float = 0.0,
        mode: str = "hybrid",
        alpha: float = 0.4,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []

        matched = _matched_entities(self.project, query)

        if mode == "keyword":
            items = self._search_lexical(query, kinds, chapter_limit, top_k * 2)
            items = self._route_entities(items, matched, "lexical_score", kinds)
            items.sort(key=lambda item: float(item.get("lexical_score") or 0.0), reverse=True)
            return _normalize(_dedupe_hits(items), "lexical_score", top_k, threshold)

        if mode == "vector":
            items = self._search_vector(query, kinds, chapter_limit, top_k * 2)
            items = self._route_entities(items, matched, "vector_score", kinds)
            items.sort(key=lambda item: float(item.get("vector_score") or 0.0), reverse=True)
            results = []
            for item in _dedupe_hits(items):
                score = max(0.0, float(item["vector_score"]))
                if score >= threshold:
                    results.append(
                        {**item, "score": round(score, 4), "raw_score": round(score, 4)}
                    )
            return results[:top_k]

        lexical = self._search_lexical(query, kinds, chapter_limit, top_k * 2)
        vector_hits = self._search_vector(query, kinds, chapter_limit, top_k * 2)

        alpha = min(max(alpha, 0.0), 1.0)
        fused: dict[str, dict[str, Any]] = {}
        for rank, item in enumerate(lexical):
            entry = fused.setdefault(item["id"], {**item, "score": 0.0})
            entry["score"] += alpha / (60 + rank + 1)
        for rank, item in enumerate(vector_hits):
            entry = fused.setdefault(item["id"], {**item, "score": 0.0})
            entry["score"] += (1 - alpha) / (60 + rank + 1)
            entry.setdefault("vector_score", item["vector_score"])

        ranked = sorted(fused.values(), key=lambda item: item["score"], reverse=True)
        ranked = self._route_entities(ranked, matched, "score", kinds)
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return _normalize(_dedupe_hits(ranked), "score", top_k, threshold)

    def list_chunks(
        self,
        kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
        query: str | None = None,
    ) -> dict[str, Any]:
        sql = ["SELECT * FROM chunks WHERE 1=1"]
        params: list[Any] = []
        if kind:
            sql.append("AND kind = ?")
            params.append(kind)
        if query:
            sql.append("AND (title LIKE ? OR text LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like])
        sql.append("ORDER BY kind ASC, chapter ASC, id ASC LIMIT ? OFFSET ?")
        params.extend([limit, offset])

        with self.connect() as conn:
            rows = conn.execute(" ".join(sql), params).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM chunks" + (" WHERE kind = ?" if kind else ""),
                ([kind] if kind else []),
            ).fetchone()["n"]

        return {
            "total": total,
            "items": [
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "ref": row["ref"],
                    "title": row["title"],
                    "text": row["text"],
                    "chapter": row["chapter"],
                    "source": row["source"],
                }
                for row in rows
            ],
        }

    def stats_by_kind(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT kind, COUNT(*) AS n FROM chunks GROUP BY kind"
            ).fetchall()
        return {row["kind"]: row["n"] for row in rows}

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
        for index, row in enumerate(rows):
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
                    # bm25 的绝对值随语料规模漂移（小语料里只有 1e-6），
                    # 界面上展示名次比展示分数更有意义
                    "lexical_rank": index + 1,
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

        sql = ["SELECT chunk_id, distance FROM vec_chunks WHERE embedding MATCH ? AND k = ?"]
        params: list[Any] = [_pack(query_vector), max(limit, 1)]
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            sql.append(f"AND kind IN ({placeholders})")
            params.extend(kinds)
        if chapter_limit:
            sql.append("AND chapter <= ?")
            params.append(chapter_limit)
        sql.append("ORDER BY distance")

        try:
            with self.connect() as conn:
                hits = conn.execute(" ".join(sql), params).fetchall()
                if not hits:
                    return []
                ids = [hit["chunk_id"] for hit in hits]
                placeholders = ",".join("?" for _ in ids)
                rows = conn.execute(
                    f"SELECT * FROM chunks WHERE id IN ({placeholders})", ids
                ).fetchall()
        except sqlite3.OperationalError as exc:
            # 向量表还没建（首次开启向量但未重建索引）：降级为空，关键词仍然可用
            self.last_vector_error = f"向量索引不可用：{exc}"
            return []

        by_id = {row["id"]: row for row in rows}
        results: list[dict[str, Any]] = []
        for hit in hits:
            row = by_id.get(hit["chunk_id"])
            if row is None:
                continue
            # vec0 的 cosine distance = 1 - cos，换成相似度便于和阈值对齐
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
                    "vector_score": 1.0 - float(hit["distance"]),
                }
            )
        return results

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
            embedded = 0
            dim = 0
            if _vec_table_exists(conn):
                embedded = conn.execute("SELECT COUNT(*) AS n FROM vec_chunks").fetchone()["n"]
                dim = _meta_int(conn, "vec_dim")
        provider = (self.embedding.provider or "none").lower()
        model = (
            self.embedding.local_model
            if provider == "local"
            else self.embedding.model
            if provider == "openai"
            else ""
        )
        # 本地模型的维度是已知的：和索引里的实际维度对不上就说明要重建
        expected_dim = int((LOCAL_MODELS.get(model) or {}).get("dim") or 0) if provider == "local" else 0
        return {
            "chunks": total,
            "embedded": embedded,
            "provider": provider,
            "model": model,
            "dim": dim,
            "expected_dim": expected_dim,
            "backend": "sqlite-vec" if sqlite_vec is not None else "none",
            "error": self.last_vector_error,
        }


def _load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    if sqlite_vec is None or not hasattr(conn, "enable_load_extension"):
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:  # noqa: BLE001 - 加载失败就只做关键词检索
        return False


def _meta_int(conn: sqlite3.Connection, key: str) -> int:
    row = conn.execute("SELECT value FROM index_meta WHERE key = ?", (key,)).fetchone()
    try:
        return int(row["value"]) if row else 0
    except (TypeError, ValueError):
        return 0


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)", (key, value))


def _vec_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'vec_chunks'"
    ).fetchone()
    return bool(row)


def _ensure_vec_table(
    conn: sqlite3.Connection, dim: int, model: str, provider: str
) -> bool:
    """保证 vec0 表存在且维度匹配。

    vec0 的维度建表时固定，换嵌入模型只能重建；这里发现不一致就重建空表，
    并把 vec_dim / vec_model 写回 meta，由 stats() 暴露给界面提示「需重建」。
    """
    if not _load_sqlite_vec(conn):
        return False
    current = _meta_int(conn, "vec_dim")
    exists = _vec_table_exists(conn)
    if exists and current == dim:
        return True
    if exists:
        conn.execute("DROP TABLE vec_chunks")
    conn.execute(
        "CREATE VIRTUAL TABLE vec_chunks USING vec0("
        "chunk_id TEXT PRIMARY KEY, "
        "kind TEXT partition key, "
        "chapter INTEGER, "
        f"embedding FLOAT[{dim}] distance_metric=cosine)"
    )
    _meta_set(conn, "vec_dim", str(dim))
    _meta_set(conn, "vec_model", f"{provider}:{model}")
    conn.commit()
    return True


def _delete_vector(conn: sqlite3.Connection, chunk_id: str) -> None:
    if _vec_table_exists(conn):
        conn.execute("DELETE FROM vec_chunks WHERE chunk_id = ?", (chunk_id,))


def _insert_chunk(conn: sqlite3.Connection, chunk: Chunk) -> None:
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


def _normalize(
    items: list[dict[str, Any]], key: str, top_k: int, threshold: float
) -> list[dict[str, Any]]:
    """把原始分归一到「相对最高分」的 0-1，同时保留 raw_score。

    阈值是按相对分过滤的（0 表示不过滤）；保留原始分是为了排查检索质量，
    也避免用户把 1.000 误读成「绝对相关」。
    """
    if not items:
        return []
    max_value = max(float(item.get(key) or 0.0) for item in items) or 1.0
    results = []
    for item in items:
        raw = float(item.get(key) or 0.0)
        score = raw / max_value
        if score < threshold:
            continue
        results.append({**item, "score": round(score, 4), "raw_score": round(raw, 4)})
    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:top_k]


def _entity_alias_map(project: Path) -> dict[str, tuple[str, str]]:
    """收集「名字/别名 → 实体」的映射，供查询里的实体路由使用。

    带 TTL 缓存：检索是高频动作，但实体卡不是每分钟都在变；
    写入路径会调 `invalidate_entities()` 立刻清掉缓存。
    """
    key = str(project.resolve())
    now = time.monotonic()
    cached = _ENTITY_CACHE.get(key)
    if cached and now - cached[0] < _ENTITY_TTL:
        return cached[1]

    mapping: dict[str, tuple[str, str]] = {}
    for kind in KINDS:
        directory = project / "kb" / kind
        if not directory.exists():
            continue
        for file in directory.glob("*.md"):
            try:
                meta, _ = parse_note(read_text(file))
            except OSError:
                continue
            entity_id = str(meta.get("id") or file.stem)
            names: list[str] = [str(meta.get("name") or file.stem)]
            aliases = meta.get("aliases") or meta.get("alias") or []
            if isinstance(aliases, str):
                aliases = [item.strip() for item in _ALIAS_SPLIT.split(aliases) if item.strip()]
            names.extend(str(item) for item in aliases)
            for name in names:
                name = name.strip()
                if name:
                    mapping.setdefault(name, (kind, entity_id))
    _ENTITY_CACHE[key] = (now, mapping)
    return mapping


def invalidate_entities(project: Path | None = None) -> None:
    """知识库写入后调用：下一次检索重新扫描实体名。"""
    if project is None:
        _ENTITY_CACHE.clear()
        return
    _ENTITY_CACHE.pop(str(project.resolve()), None)


def _matched_entities(project: Path, query: str) -> set[tuple[str, str]]:
    """查询里点名了哪些实体。

    名字按子串匹配：「林昭的剑」命中「林昭」，「晦是什么东西」命中单字别名「晦」。
    单字名会命中更多噪声，所以虚词一律不参与（见 `_NAME_STOPWORDS`）。
    """
    mapping = _entity_alias_map(project)
    if not mapping:
        return set()
    matched: set[tuple[str, str]] = set()
    for name, target in mapping.items():
        if not name or name in _NAME_STOPWORDS:
            continue
        if name in query:
            matched.add(target)
    return matched


def _dedupe_hits(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一张实体卡拆成多个切片时只留最高分那一段；章节切片不去重。

    不这么做的话，一个长角色卡会在结果里连刷好几条同名命中，挤掉别的资料。
    """
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        if item.get("kind") == "chapters":
            result.append(item)
            continue
        key = (str(item.get("kind")), str(item.get("ref")))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _split_entity(title: str, body: str, max_len: int = 700) -> list[str]:
    """实体卡切片：短卡整张保留，长卡按二级标题拆小节。

    角色卡的「外貌 / 性格 / 成长路线」放在一个切片里会被嵌入模型截断，
    拆开之后「他是什么性格」这类问题才能命中对应小节。
    """
    body = (body or "").strip()
    title = (title or "").strip()
    if not body:
        return [title] if title else []
    if len(body) <= max_len:
        return [f"{title}\n{body}".strip()]

    parts = re.split(r"(?m)^(#{2,6}\s+.+)$", body)
    sections: list[str] = []
    if parts[0].strip():
        sections.append(parts[0].strip())
    for index in range(1, len(parts), 2):
        heading = parts[index].strip()
        content = parts[index + 1].strip() if index + 1 < len(parts) else ""
        sections.append(f"{heading}\n{content}".strip())

    pieces: list[str] = []
    buffer = ""
    for section in sections:
        if not section:
            continue
        if len(buffer) + len(section) + 1 <= max_len:
            buffer = f"{buffer}\n{section}".strip()
            continue
        if buffer:
            pieces.append(buffer)
            buffer = ""
        if len(section) <= max_len:
            buffer = section
        else:
            pieces.extend(_split_text(section, max_len=max_len, overlap=60))
    if buffer:
        pieces.append(buffer)
    return [f"{title}\n{piece}".strip() for piece in pieces] or [f"{title}\n{body[:max_len]}"]


def _split_text(text: str, max_len: int = 480, overlap: int = 60) -> list[str]:
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


DEFAULT_KB_CONFIG: dict[str, Any] = {
    "top_k": 8,
    "threshold": 0.0,
    "mode": "hybrid",
    "alpha": 0.4,
    "chapter_limit": None,
}


def load_kb_config(project: Path) -> dict[str, Any]:
    file = project / "kb" / "config.json"
    merged = dict(DEFAULT_KB_CONFIG)
    if not file.exists():
        return merged
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return merged
    if isinstance(data, dict):
        merged.update({key: data[key] for key in DEFAULT_KB_CONFIG if key in data})
    return merged


def save_kb_config(project: Path, config: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_KB_CONFIG)
    merged.update({key: config[key] for key in DEFAULT_KB_CONFIG if key in config})
    directory = project / "kb"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return merged
