from __future__ import annotations

import re

import jieba

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """切词，供 FTS5 使用（知识库与消息回忆共用）。"""
    tokens = [t.strip() for t in jieba.cut_for_search(text) if t.strip()]
    return [t for t in tokens if _TOKEN_RE.fullmatch(t)]


def fts_query(query: str, limit: int = 24) -> str:
    tokens = tokenize(query)
    if not tokens:
        tokens = [t for t in [_TOKEN_RE.sub("", query)] if t]
    unique = list(dict.fromkeys(tokens))
    return " OR ".join(f'"{t}"' for t in unique[:limit])


def clip(text: str, limit: int) -> tuple[str, bool]:
    """按字符截断，返回 (文本, 是否被截断)。"""
    text = text.strip()
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip() + "\n…（已截断）", True
