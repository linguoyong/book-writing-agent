"""一次性迁移：把书稿与记忆里的 CRLF/CR 统一成 LF。

背景：旧版本在 Windows 上「读—改—写」会保留磁盘上的 `\\r\\n`，
而 `Path.write_text()` 又会把 `\\n` 翻成 `\\r\\n`，于是每写一次就多一层 `\\r`。
新代码已在读写两端归一化，这个脚本负责把历史文件清理干净。

用法（在 server/ 下执行）：

    uv run python scripts/normalize_newlines.py           # 只统计，不落盘
    uv run python scripts/normalize_newlines.py --apply   # 真正改写

只处理 `~/.book-agent/books/**` 与 `~/.book-agent/memory/**` 下的 `.md` / `.json`，
跳过 `.git`、`.index` 与 `node_modules`，并保留原文件编码（UTF-8 / GB18030）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import BOOKS_DIR, MEMORY_DIR  # noqa: E402
from app.text import normalize_newlines, save_text  # noqa: E402

SKIP_PARTS = {".git", ".index", "node_modules", "__pycache__", ".venv"}
SUFFIXES = {".md", ".json"}


def decode_with_encoding(raw: bytes) -> tuple[str, str]:
    """按与 read_text 相同的顺序解码，但保留命中的编码，便于原样写回。"""
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


def iter_files() -> list[Path]:
    files: list[Path] = []
    for root in (BOOKS_DIR, MEMORY_DIR):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUFFIXES:
                continue
            if SKIP_PARTS & set(path.parts):
                continue
            files.append(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="把书稿 Markdown 的换行统一成 LF")
    parser.add_argument("--apply", action="store_true", help="真正写回磁盘（默认只统计）")
    args = parser.parse_args()

    total = 0
    dirty = 0
    removed = 0
    before_bytes = 0
    after_bytes = 0

    for path in iter_files():
        total += 1
        raw = path.read_bytes()
        if b"\r" not in raw:
            continue

        text, encoding = decode_with_encoding(raw)
        cleaned = normalize_newlines(text)
        cr_count = raw.count(b"\r")
        dirty += 1
        removed += cr_count
        before_bytes += len(raw)
        after_bytes += len(cleaned.encode("utf-8"))
        print(f"  {path}  去掉 {cr_count} 个 CR  ({len(raw)} → {len(cleaned.encode('utf-8'))} 字节)")

        if args.apply:
            write_encoding = "utf-8" if encoding == "utf-8-sig" else encoding
            save_text(path, cleaned, encoding=write_encoding)

    verb = "已改写" if args.apply else "待改写"
    print()
    print(f"扫描 {total} 个文件，其中 {dirty} 个含 CR，共 {removed} 处。")
    if dirty:
        print(f"{verb}：{before_bytes} → {after_bytes} 字节（减少 {before_bytes - after_bytes}）")
    if not args.apply and dirty:
        print("确认无误后加 --apply 执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
