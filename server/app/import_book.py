from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .text import decode_bytes, save_text

MAX_BYTES = 50 * 1024 * 1024
MAX_CHAPTERS = 3000
MAX_TITLE = 40

# 行首的章节标记。卷只作为分隔，不单独成章；标题行本身限制在 40 字以内，
# 避免把正文里恰好以「第一章」开头的句子当成标题。
DEFAULT_PATTERN = (
    r"^\s*(?:"
    r"第\s*[0-9零一二三四五六七八九十百千万两]+\s*[章回节篇]"
    # 这几个词必须自成标题：「序章正文。」这类句子不能因为以「序章」开头就切章
    r"|(?:序章|楔子|引子|尾声|后记|番外[一二三四五六七八九十0-9]*)(?=\s|$|[:：])"
    r"|Chapter\s+\d+"
    r")"
)

_ILLEGAL_NAME = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_CHAPTER_NO = re.compile(r"第\s*([0-9零一二三四五六七八九十百千两]+)\s*[章回节篇]")
_CN_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


class ImportError(RuntimeError):
    """导入失败（文件过大、编码无法识别、没有正文）。"""


@dataclass
class ChapterDraft:
    index: int
    title: str
    body: str
    included: bool = True
    head: str = ""
    tail: str = ""

    @property
    def chars(self) -> int:
        return len(self.body)


@dataclass
class ParsedBook:
    text: str
    encoding: str
    chapters: list[ChapterDraft] = field(default_factory=list)
    preamble_chars: int = 0


def parse_book(path: Path, pattern: str = "") -> ParsedBook:
    if not path.exists() or not path.is_file():
        raise ImportError(f"文件不存在：{path}")
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise ImportError(
            f"文件过大：{size / 1024 / 1024:.1f}MB，上限 {MAX_BYTES // 1024 // 1024}MB"
        )

    text, encoding = decode_bytes(path.read_bytes())
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise ImportError("文件内容为空")

    regex = _compile(pattern)
    chapters, preamble = _split(text, regex)
    if not chapters:
        chapters = _fallback_split(text)
    if not chapters:
        raise ImportError("没有识别到正文")

    if len(chapters) > MAX_CHAPTERS:
        # 以前是静默截断：用户看到「导入成功 3000 章」，后面的章节直接没了。
        raise ImportError(
            f"识别到 {len(chapters)} 章，超过单次导入上限 {MAX_CHAPTERS} 章；"
            "请先按卷拆分文件，或调整章节标记后分批导入。"
        )
    return ParsedBook(
        text=text,
        encoding=encoding,
        chapters=chapters,
        preamble_chars=len(preamble.strip()),
    )


def _compile(pattern: str) -> re.Pattern[str]:
    source = (pattern or "").strip() or DEFAULT_PATTERN
    try:
        return re.compile(source)
    except re.error as exc:
        raise ImportError(f"章节规则不是合法正则：{exc}") from exc


def _is_heading(line: str, regex: re.Pattern[str]) -> bool:
    stripped = line.strip()
    return bool(stripped) and len(stripped) <= MAX_TITLE + 10 and bool(regex.match(stripped))


def _split(text: str, regex: re.Pattern[str]) -> tuple[list[ChapterDraft], str]:
    lines = text.split("\n")
    marks: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if _is_heading(line, regex):
            marks.append((index, line.strip()))
    if not marks:
        return [], text

    preamble = "\n".join(lines[: marks[0][0]])
    chapters: list[ChapterDraft] = []
    for position, (line_index, title) in enumerate(marks):
        end = marks[position + 1][0] if position + 1 < len(marks) else len(lines)
        body = "\n".join(lines[line_index + 1 : end]).strip()
        chapters.append(_draft(len(chapters), title, body))

    # 卷首的版权、简介等：够长才单独成篇，短的就丢掉
    if len(preamble.strip()) >= 800:
        chapters.insert(0, _draft(0, "开篇", preamble.strip()))
        for offset, chapter in enumerate(chapters):
            chapter.index = offset
    return chapters, preamble


def _fallback_split(text: str) -> list[ChapterDraft]:
    """完全没有章节标记时，按段落切成约 3000 字一节，至少能导入并检索。"""
    paragraphs = [p for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paragraphs:
        return []
    chapters: list[ChapterDraft] = []
    buffer: list[str] = []
    length = 0
    for paragraph in paragraphs:
        buffer.append(paragraph)
        length += len(paragraph)
        if length >= 3000:
            chapters.append(_draft(len(chapters), f"第{len(chapters) + 1}节", "\n\n".join(buffer)))
            buffer, length = [], 0
    if buffer:
        chapters.append(_draft(len(chapters), f"第{len(chapters) + 1}节", "\n\n".join(buffer)))
    return chapters


def _draft(index: int, title: str, body: str) -> ChapterDraft:
    flat = re.sub(r"\s+", " ", body)
    return ChapterDraft(
        index=index,
        title=title.strip(),
        body=body,
        head=flat[:80],
        tail=flat[-80:],
    )


def chapter_number_from_title(title: str) -> int | None:
    """标题里自带的章号（第002章 / 第十二回）优先，保证与原文编号一致。"""
    match = _CHAPTER_NO.search(title)
    if not match:
        return None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    section = 0
    number = 0
    for char in raw:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
        elif char in _CN_UNITS:
            section += (number or 1) * _CN_UNITS[char]
            number = 0
        else:
            return None
    total = section + number
    return total or None


def sanitize_name(title: str) -> str:
    cleaned = _ILLEGAL_NAME.sub(" ", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:MAX_TITLE] or "未命名"


def preview(path: Path, pattern: str = "") -> dict[str, Any]:
    parsed = parse_book(path, pattern)
    return {
        "file": path.name,
        "encoding": parsed.encoding,
        "total_chars": len(parsed.text),
        "preamble_chars": parsed.preamble_chars,
        "chapters": [
            {
                "index": chapter.index,
                "title": chapter.title,
                "chars": chapter.chars,
                "head": chapter.head,
                "tail": chapter.tail,
            }
            for chapter in parsed.chapters
        ],
    }


def existing_numbers(chapters_dir: Path) -> set[int]:
    numbers: set[int] = set()
    if chapters_dir.exists():
        for file in chapters_dir.glob("*.md"):
            match = re.match(r"(\d+)", file.stem)
            if match:
                numbers.add(int(match.group(1)))
    return numbers


def find_start_number(chapters_dir: Path) -> int:
    """已有章节的最大编号 +1，导入不覆盖既有内容。"""
    largest = 0
    if chapters_dir.exists():
        for file in chapters_dir.glob("*.md"):
            match = re.match(r"(\d+)", file.stem)
            if match:
                largest = max(largest, int(match.group(1)))
    return largest + 1


def commit(
    project: Path,
    source: Path,
    *,
    pattern: str = "",
    excluded: list[int] | None = None,
    titles: dict[str, str] | None = None,
) -> dict[str, Any]:
    parsed = parse_book(source, pattern)
    excluded_set = set(excluded or [])
    overrides = titles or {}

    selected = [
        (chapter, overrides.get(str(chapter.index), chapter.title))
        for chapter in parsed.chapters
        if chapter.index not in excluded_set and chapter.body.strip()
    ]
    if not selected:
        raise ImportError("没有可导入的章节（可能全被排除了）")

    chapters_dir = project / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    start = find_start_number(chapters_dir)
    imported_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    written: list[dict[str, Any]] = []
    # 已存在的章号也算占用，否则重名会把旧文件覆盖掉
    used: set[int] = existing_numbers(chapters_dir)
    # 先把标题里写死的章号占住：否则「开篇」这类无编号章节会抢走 1 号，
    # 把真正的「第一章」顶成 2，之后全书章号整体偏移一章。
    reserved = {
        number for _, title in selected if (number := chapter_number_from_title(title)) is not None
    }
    next_number = start
    # 卷首/序章这类没有阿拉伯章号的，排到正文之前（0 或负数），
    # 尾声/后记/番外则排到正文之后，都不占用正文章号。
    front_after = max([start - 1, *reserved]) + 1
    for chapter, title in selected:
        # 正文标题里的章号优先，避免「第002章」被写成 0001 导致排序错乱
        number = chapter_number_from_title(title)
        if number is None:
            if title.strip() in {"开篇", "序章", "楔子", "引子"}:
                number = 0
                while number in used:
                    number -= 1
            else:
                number = front_after
                while number in used or number in reserved:
                    number += 1
                front_after = number + 1
        elif number in used:
            number = next_number
            while number in used or number in reserved:
                number += 1
        used.add(number)
        next_number = max(next_number, number + 1)
        name = f"{number:04d}-{sanitize_name(title)}.md"
        meta = {
            "chapter": number,
            "title": title,
            "source": source.name,
            "imported_at": imported_at,
        }
        body = _dump_note(meta, chapter.body)
        save_text(chapters_dir / name, body)
        written.append({"number": number, "title": title, "file": f"chapters/{name}"})

    return {
        "imported": len(written),
        "skipped": len(parsed.chapters) - len(selected),
        "encoding": parsed.encoding,
        "first": written[0]["title"],
        "last": written[-1]["title"],
        "files": written,
    }


def _dump_note(meta: dict[str, Any], body: str) -> str:
    """章节文件也用 front-matter，检索与 lint 靠它拿章节号。"""
    lines = ["---"]
    for key, value in meta.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + body.rstrip() + "\n"
