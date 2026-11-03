from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .kb.repository import parse_note
from .text import read_text
from .workspace import read_book_meta

ILLEGAL_NAME = re.compile(r'[\\/:*?"<>|\r\n\t]+')
HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*$")
NUMBER_PREFIX = re.compile(r"^\d+[-_\s]*")


class ExportError(RuntimeError):
    """导出失败，消息可直接展示给用户。"""


def _natural_key(value: str) -> list[Any]:
    """ch-2 排在 ch-10 前面；纯字典序会把第十章提到第二章之前。"""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def chapter_files(project: Path) -> list[tuple[str, Path]]:
    manuscript = project / "manuscript"
    if not manuscript.exists():
        return []
    files: list[tuple[str, Path]] = []
    for file in manuscript.rglob("*.md"):
        parts = file.relative_to(manuscript).parts
        # outline 是大纲，不该进正文；下划线开头的是内部文件
        if parts and parts[0] == "outline":
            continue
        if any(part.startswith("_") or part.startswith(".") for part in parts):
            continue
        files.append(("/".join(parts), file))
    files.sort(key=lambda item: [_natural_key(part) for part in item[0].split("/")])
    return files


def _clean_title(path: Path, meta: dict[str, Any], body: str) -> str:
    title = str(meta.get("title") or "").strip()
    if title:
        return title
    for line in body.splitlines():
        match = HEADING.match(line.strip())
        if match:
            return match.group(1).strip()
        if line.strip():
            break
    return NUMBER_PREFIX.sub("", path.stem).replace("-", " ").strip() or path.stem


def _clean_body(body: str, title: str) -> str:
    """去掉正文开头重复的标题：`# 第N章` 与裸标题都算。"""
    lines = body.splitlines()
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines):
        stripped = lines[index].strip()
        match = HEADING.match(stripped)
        candidate = match.group(1).strip() if match else stripped
        if candidate == title:
            lines = lines[:index] + lines[index + 1 :]
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def collect(project: Path) -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    for relative, file in chapter_files(project):
        try:
            meta, body = parse_note(read_text(file))
        except OSError:
            continue
        title = _clean_title(file, meta, body)
        text = _clean_body(body, title)
        if not text.strip():
            continue
        chapters.append(
            {
                "file": relative,
                "volume": relative.split("/")[0] if "/" in relative else "",
                "title": title,
                "body": text,
                "chars": len(re.sub(r"\s", "", text)),
            }
        )
    return chapters


def _volume_label(volume: str) -> str:
    """`vol-02` → 第2卷；已经是中文名的目录原样使用。"""
    match = re.search(r"(\d+)", volume)
    return f"第{int(match.group(1))}卷" if match else volume


def build_txt(
    chapters: list[dict[str, Any]],
    *,
    book_title: str = "",
    author: str = "",
    include_toc: bool = False,
) -> str:
    if not chapters:
        raise ExportError("还没有成稿章节，先在 manuscript/ 下写点正文")

    blocks: list[str] = []
    if book_title.strip():
        head = book_title.strip()
        if author.strip():
            head += f"\n作者：{author.strip()}"
        blocks.append(head)

    if include_toc:
        lines = ["目录", ""]
        for index, chapter in enumerate(chapters, start=1):
            lines.append(f"{index}. {chapter['title']}")
        blocks.append("\n".join(lines))

    # 单卷不额外加「第1卷」，多卷才恢复卷结构
    volumes = {str(chapter.get("volume") or "") for chapter in chapters}
    volumes.discard("")
    show_volumes = len(volumes) > 1
    current_volume = ""
    for chapter in chapters:
        volume = str(chapter.get("volume") or "")
        if show_volumes and volume and volume != current_volume:
            current_volume = volume
            blocks.append(_volume_label(volume))
        blocks.append(f"{chapter['title']}\n\n{chapter['body']}")
    return "\n\n\n".join(blocks).strip() + "\n"


def default_name(project: Path) -> str:
    meta = read_book_meta(project)
    title = str(meta.get("title") or project.name)
    stamp = datetime.now().strftime("%Y%m%d")
    safe = ILLEGAL_NAME.sub(" ", title).strip() or "成稿"
    return f"{safe}-{stamp}.txt"


def export_txt(
    project: Path,
    *,
    target: str = "",
    encoding: str = "utf-8",
    include_toc: bool = False,
) -> dict[str, Any]:
    chapters = collect(project)
    meta = read_book_meta(project)
    text = build_txt(
        chapters,
        book_title=str(meta.get("title") or ""),
        author=str(meta.get("author") or ""),
        include_toc=include_toc,
    )

    if encoding not in ("utf-8", "utf-8-sig", "gb18030"):
        raise ExportError(f"不支持的编码：{encoding}")

    if target.strip():
        path = Path(target).expanduser()
        if not path.is_absolute():
            path = project / path
        if path.suffix.lower() != ".txt":
            path = path.with_suffix(".txt")
    else:
        path = project / "exports" / default_name(project)

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # gb18030 覆盖全部 Unicode（含 emoji 与扩展区），不需要 errors="replace"
        data = text.encode(encoding)
        path.write_bytes(data)
    except OSError as exc:
        raise ExportError(f"写入失败：{exc}") from exc

    return {
        "path": str(path),
        "name": path.name,
        "chapters": len(chapters),
        "chars": sum(chapter["chars"] for chapter in chapters),
        "bytes": len(data),
        "encoding": encoding,
        "first": chapters[0]["title"],
        "last": chapters[-1]["title"],
    }
