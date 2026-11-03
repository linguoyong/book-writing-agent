from __future__ import annotations

import contextlib
import os
import re
import tempfile
from pathlib import Path

import charset_normalizer
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


def _plausible(text: str) -> float:
    """可读字符占比：ASCII 可打印、CJK、中文标点、全角符号算「像正常文本」。"""
    sample = text[:2048]
    if not sample:
        return 0.0
    good = 0
    for char in sample:
        code = ord(char)
        if (
            char in "\n\r\t"
            or 0x20 <= code <= 0x7E
            or 0x4E00 <= code <= 0x9FFF
            or 0x3000 <= code <= 0x303F
            or 0xFF00 <= code <= 0xFFEF
        ):
            good += 1
    return good / len(sample)


def _decode_utf16_without_bom(raw: bytes) -> str | None:
    """无 BOM 的 UTF-16 在 GB18030 下也能「解码成功」，只会得到一串乱码。

    不能只看 NUL 比例：中文 UTF-16 里 `一`(U+4E00) 这类字的低字节就是 0，
    纯中文段落几乎没有连续的 0。这里把两种字节序都试一遍，用「可读字符占比」
    和 GB18030 假设做对比，只有明显更像 UTF-16 才采纳。
    """
    sample = raw[:65536]
    if len(sample) < 8:
        return None
    if len(sample) % 2:
        sample = sample[:-1]

    best: tuple[float, str] | None = None
    for encoding in ("utf-16-le", "utf-16-be"):
        try:
            text = sample.decode(encoding)
        except UnicodeDecodeError:
            # 落单的代理项基本可以判定不是这个字节序
            continue
        score = _plausible(text)
        if best is None or score > best[0]:
            best = (score, encoding)
    if best is None or best[0] < 0.95:
        return None

    # GB18030 几乎能解释任何字节；只有它明显更差时才认定是 UTF-16
    legacy = sample.decode("gb18030", errors="replace")
    if _plausible(legacy) >= best[0] - 0.05:
        return None
    try:
        return raw.decode(best[1])
    except UnicodeDecodeError:
        return None


# 只接受东亚编码的猜测：短样本上 charset-normalizer 也会给出 cp1252 之类的答案，
# 对中文书稿没有意义。
_LEGACY_ENCODINGS = {
    "gb18030",
    "gbk",
    "gb2312",
    "big5",
    "big5hkscs",
    "cp932",
    "shift_jis",
    "euc_jp",
    "euc_kr",
}


def _guess_legacy(raw: bytes) -> tuple[str, str] | None:
    """GB18030 几乎能解码任何字节，Big5 / Shift-JIS 会被它解成乱码。

    用 charset-normalizer 在样本上猜一次；只有 chaos（混乱度）足够低、
    且猜中的是东亚编码时才采纳。
    """
    sample = raw[:16384]
    if len(sample) < 32:
        return None
    try:
        best = charset_normalizer.from_bytes(sample).best()
    except Exception:  # noqa: BLE001
        return None
    if best is None or not best.encoding:
        return None
    encoding = str(best.encoding).lower()
    if encoding not in _LEGACY_ENCODINGS:
        return None
    if (getattr(best, "chaos", 1.0) or 0.0) > 0.1:
        return None
    try:
        return normalize_newlines(raw.decode(encoding)), encoding
    except (LookupError, UnicodeDecodeError):
        return None


def decode_bytes(raw: bytes) -> tuple[str, str]:
    """按 BOM → 无 BOM 的 UTF-16 → UTF-8 → GB18030 解码，返回 (文本, 编码名)。

    顺序很重要：gb18030 几乎能解码任意字节序列，放在 UTF-16 前面就会把
    UTF-16 文件解成一串夹着 NUL 的乱码而不报错。
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return normalize_newlines(raw[3:].decode("utf-8", errors="replace")), "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return normalize_newlines(raw.decode("utf-16")), "utf-16"
        except UnicodeDecodeError:
            pass
    utf16 = _decode_utf16_without_bom(raw)
    if utf16 is not None:
        return normalize_newlines(utf16), "utf-16"
    try:
        return normalize_newlines(raw.decode("utf-8")), "utf-8"
    except UnicodeDecodeError:
        pass
    guessed = _guess_legacy(raw)
    if guessed is not None:
        return guessed
    try:
        return normalize_newlines(raw.decode("gb18030")), "gb18030"
    except UnicodeDecodeError:
        return normalize_newlines(raw.decode("utf-8", errors="replace")), "utf-8(替换非法字节)"


def read_text(path: Path | str) -> str:
    """读用户文本：编码探测 + 换行统一为 LF。

    书稿常见 GBK/GB18030，也可能是从 Word/网页另存的 UTF-16；
    单个文件编码不对不该让检索、上下文装配或 lint 整体 500。
    """
    return decode_bytes(Path(path).read_bytes())[0]


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
