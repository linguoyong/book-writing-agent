from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .export_book import chapter_files
from .kb.repository import parse_note
from .text import read_text, save_text
from .workspace import read_book_meta, write_book_meta

CACHE_FILE = "stats.json"
_SPACE = re.compile(r"\s")
_NUMBER = re.compile(r"(\d+)")


def count_words(text: str) -> int:
    """中文字数按「非空白字符」算，和网文平台的口径一致。"""
    return len(_SPACE.sub("", text or ""))


def _chapter_number(meta: dict[str, Any], path: Path) -> int:
    for key in ("chapter", "index", "number"):
        value = meta.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    match = _NUMBER.search(path.stem)
    return int(match.group(1)) if match else 0


def _signature(project: Path) -> str:
    """用「文件数 + 总大小 + 最大 mtime」判断缓存是否失效，比逐个读文件便宜得多。"""
    count = 0
    total = 0
    latest = 0.0
    for _, file in chapter_files(project):
        try:
            stat = file.stat()
        except OSError:
            continue
        count += 1
        total += stat.st_size
        latest = max(latest, stat.st_mtime)
    return f"{count}:{total}:{int(latest)}"


def _cache_path(project: Path) -> Path:
    return project / ".index" / CACHE_FILE


def compute(project: Path) -> dict[str, Any]:
    signature = _signature(project)
    cache_path = _cache_path(project)
    cached: dict[str, Any] = {}
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cached = {}
    if cached.get("signature") == signature and isinstance(cached.get("stats"), dict):
        return cached["stats"]

    today = date.today().isoformat()
    chapters: list[dict[str, Any]] = []
    for relative, file in chapter_files(project):
        try:
            meta, body = parse_note(read_text(file))
            stat = file.stat()
        except OSError:
            continue
        volume_match = _NUMBER.search(relative.split("/")[0]) if "/" in relative else None
        chapters.append(
            {
                "volume": int(volume_match.group(1)) if volume_match else 1,
                "chapter": _chapter_number(meta, file),
                "title": str(meta.get("title") or file.stem),
                "words": count_words(body),
                "path": relative,
                "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "today": datetime.fromtimestamp(stat.st_mtime).date().isoformat() == today,
            }
        )

    meta = read_book_meta(project)
    total = sum(item["words"] for item in chapters)
    target = int(meta.get("target_words") or 0)
    last = chapters[-1] if chapters else None
    stats = {
        "chapters": len(chapters),
        "words": total,
        "avg_words": round(total / len(chapters)) if chapters else 0,
        "today_words": sum(item["words"] for item in chapters if item["today"]),
        "volume": int(last["volume"]) if last else 1,
        "chapter": int(last["chapter"]) if last else 0,
        "chapter_title": str(last["title"]) if last else "",
        "target_words": target,
        "progress": round(total / target, 4) if target else 0.0,
        "words_per_chapter": int(meta.get("words_per_chapter") or 0),
        "recent": [
            {"title": item["title"], "words": item["words"], "updated_at": item["updated_at"]}
            for item in chapters[-5:][::-1]
        ],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    save_text(
        cache_path,
        json.dumps({"signature": signature, "stats": stats}, ensure_ascii=False, indent=2),
    )
    return stats


def sync_progress(project: Path) -> dict[str, Any]:
    """把「写到第几章」写回 book.json，让运行态与防剧透拿到真实进度。"""
    stats = compute(project)
    meta = read_book_meta(project)
    current = meta.get("progress") or {}
    target = {"volume": stats["volume"], "chapter": stats["chapter"]}
    if current.get("volume") != target["volume"] or current.get("chapter") != target["chapter"]:
        meta["progress"] = target
        write_book_meta(project, meta)
    return stats
