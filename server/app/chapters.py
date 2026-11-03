from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .export_book import chapter_files
from .kb.repository import dump_note, parse_note
from .text import read_text, save_text


class ChapterError(RuntimeError):
    """新建章节失败，消息可直接展示给用户。"""


def _leading_number(stem: str) -> int:
    match = re.match(r"(\d+)", stem)
    return int(match.group(1)) if match else 0


def _any_number(value: str) -> int:
    """`vol-02` 这种目录名，数字不在开头。"""
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else 0


def next_position(project: Path) -> tuple[int, int]:
    """返回 (卷号, 下一章号)。章号取全书最大章号 +1，跨卷连续。"""
    volume = 1
    largest = 0
    for relative, file in chapter_files(project):
        parts = relative.split("/")
        if len(parts) > 1:
            volume = max(volume, _any_number(parts[0]) or volume)
        meta, _ = parse_note(read_text(file))
        try:
            number = int(meta.get("chapter") or 0)
        except (TypeError, ValueError):
            number = 0
        largest = max(largest, number or _leading_number(file.stem))
    return volume, largest + 1


def create(project: Path, *, title: str = "", volume: int | None = None) -> dict[str, Any]:
    volume_no, chapter_no = next_position(project)
    if volume is not None:
        volume_no = max(1, int(volume))
    if chapter_no > 9999:
        raise ChapterError(f"章号超出上限：{chapter_no}")

    safe_title = title.strip() or f"第{chapter_no}章"
    label = safe_title if safe_title.startswith("第") else f"第{chapter_no}章 {safe_title}"
    directory = project / "manuscript" / f"vol-{volume_no:02d}"
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / f"ch-{chapter_no:03d}.md"
    if file.exists():
        raise ChapterError(f"章节已存在：{file.relative_to(project)}")

    body = f"{label}\n\n"
    content = dump_note({"title": label, "chapter": chapter_no}, body)
    save_text(file, content)
    return {
        "path": str(file.relative_to(project)).replace("\\", "/"),
        "chapter": chapter_no,
        "volume": volume_no,
        "title": label,
    }
