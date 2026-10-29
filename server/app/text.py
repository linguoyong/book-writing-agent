from __future__ import annotations

import re
from pathlib import Path

import jieba

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")


def read_text(path: Path | str) -> str:
    """读用户文本：UTF-8(BOM) → GB18030 → 兜底替换非法字节。

    书稿常见 GBK/GB18030，且同一本书里可能混着不同来源的文件；
    单个文件编码不对不该让检索、上下文装配或 lint 整体 500。
    """
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


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
