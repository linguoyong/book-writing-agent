from __future__ import annotations

import contextlib
import os
import re
import tempfile
from pathlib import Path

import jieba

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")
_NEWLINE_RE = re.compile(r"\r\n?")


def normalize_newlines(text: str) -> str:
    """把 CRLF / CR 统一成 LF。

    Windows 上 `Path.write_text()` 会把每个 `\\n` 再翻译成 `\\r\\n`。如果读入时
    保留了磁盘上的 `\\r\\n`，一次「读—改—写」就会变成 `\\r\\r\\n`，再写一次变
    `\\r\\r\\r\\n`。书稿是唯一事实来源，所以入口和出口都必须统一。
    """
    return _NEWLINE_RE.sub("\n", text)


def read_text(path: Path | str) -> str:
    """读用户文本：UTF-8(BOM) → GB18030 → 兜底替换非法字节，换行统一为 LF。

    书稿常见 GBK/GB18030，且同一本书里可能混着不同来源的文件；
    单个文件编码不对不该让检索、上下文装配或 lint 整体 500。
    """
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return normalize_newlines(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    return normalize_newlines(raw.decode("utf-8", errors="replace"))


def save_text(path: Path | str, text: str, encoding: str = "utf-8") -> None:
    """原子写文本：先写同目录临时文件，再 `os.replace` 顶替。

    直接 `write_text` 有两个问题：进程在写盘途中被杀会留下半截文件；
    Windows 的换行翻译会把已含 `\\r\\n` 的文本再翻一层。这里关闭翻译，
    并保证目标文件要么是旧内容、要么是完整的新内容。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
            handle.write(normalize_newlines(text))
        os.replace(temp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp)
        raise


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
