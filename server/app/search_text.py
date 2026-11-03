from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import load_settings
from .export_book import chapter_files
from .sandbox import check_path
from .text import read_text, save_text
from .workspace import safe_join

_FRONT_MATTER = re.compile(r"^---\r?\n[\s\S]*?\r?\n---\r?\n?")
MAX_FILES = 400
MAX_RESULTS = 200
SNIPPET = 42


class SearchError(RuntimeError):
    """搜索/替换失败，消息可直接展示给用户。"""


def _guard(project: Path, target: Path, operation: str, sandbox: Any) -> bool:
    """与 Agent 工具、REST 文件接口共用同一套路径规则。"""
    try:
        # 两侧都 resolve：Windows 临时目录的 8.3 短名会让相对路径算不出来
        relative = target.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        return False
    return check_path(sandbox, relative, operation) != "deny"


def _files(project: Path, scope: str, path: str | None, operation: str = "read") -> list[Path]:
    sandbox = load_settings().sandbox
    if path:
        try:
            target = safe_join(project, path)
        except ValueError as exc:
            raise SearchError(f"文件不存在：{path}") from exc
        if not target.is_file() or not _guard(project, target, operation, sandbox):
            raise SearchError(f"文件不存在：{path}")
        return [target]
    result: list[Path] = []
    if scope in ("manuscript", "all"):
        result.extend(file for _, file in chapter_files(project))
    if scope in ("chapters", "all"):
        directory = project / "chapters"
        if directory.exists():
            result.extend(sorted(directory.glob("*.md")))
    # 范围检索同样要跳过被 deny 的文件（.env、私钥、secrets/**），
    # 否则预览里就能把内容拼出来。
    return [file for file in result if _guard(project, file, operation, sandbox)][:MAX_FILES]


def _pattern(query: str, regex: bool, ignore_case: bool) -> re.Pattern[str]:
    if not query or not query.strip():
        raise SearchError("请输入要查找的内容")
    source = query if regex else re.escape(query)
    flags = re.MULTILINE | (re.IGNORECASE if ignore_case else 0)
    try:
        return re.compile(source, flags)
    except re.error as exc:
        raise SearchError(f"正则表达式不合法：{exc}") from exc


def _split_front_matter(text: str) -> tuple[str, str, int]:
    """返回 (文件头, 正文, 文件头行数)。

    替换只作用于正文：改一个词不该把 front-matter 里的章节标题一起改掉。
    行号仍然按整份文件算，方便编辑器里对位置。
    """
    match = _FRONT_MATTER.match(text)
    if not match:
        return "", text, 0
    header = match.group(0)
    return header, text[len(header) :], header.count("\n")


def _relative(project: Path, file: Path) -> str:
    try:
        return str(file.relative_to(project)).replace("\\", "/")
    except ValueError:
        return str(file)


def _snippet(text: str, start: int, end: int) -> tuple[str, int]:
    line = text.count("\n", 0, start) + 1
    left = max(0, start - SNIPPET)
    right = min(len(text), end + SNIPPET)
    piece = text[left:right].replace("\n", " ").strip()
    return piece, line


def search(
    project: Path,
    query: str,
    *,
    scope: str = "manuscript",
    path: str | None = None,
    regex: bool = False,
    ignore_case: bool = False,
    limit: int = MAX_RESULTS,
) -> dict[str, Any]:
    pattern = _pattern(query, regex, ignore_case)
    items: list[dict[str, Any]] = []
    files = _files(project, scope, path, "read")
    matched_files = 0
    total = 0

    for file in files:
        try:
            text = read_text(file)
        except OSError:
            continue
        _, body, offset = _split_front_matter(text)
        found = list(pattern.finditer(body))
        if not found:
            continue
        matched_files += 1
        total += len(found)
        for match in found:
            if len(items) >= limit:
                break
            snippet, line = _snippet(body, match.start(), match.end())
            line += offset
            items.append(
                {
                    "path": _relative(project, file),
                    "line": line,
                    "snippet": snippet,
                }
            )

    return {
        "query": query,
        "total": total,
        "files": matched_files,
        "items": items,
        "truncated": total > len(items),
    }


def replace(
    project: Path,
    query: str,
    replacement: str,
    *,
    scope: str = "manuscript",
    path: str | None = None,
    regex: bool = False,
    ignore_case: bool = False,
    dry_run: bool = True,
) -> dict[str, Any]:
    if "\u0000" in replacement:
        raise SearchError("替换内容不能包含空字符")
    pattern = _pattern(query, regex, ignore_case)
    files = _files(project, scope, path, "write")
    total = 0
    changed: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []

    for file in files:
        try:
            text = read_text(file)
        except OSError:
            continue
        header, body, offset = _split_front_matter(text)
        matches = list(pattern.finditer(body))
        if not matches:
            continue
        count = len(matches)
        total += count
        changed.append({"path": _relative(project, file), "count": count})
        for match in matches[:3]:
            snippet, line = _snippet(body, match.start(), match.end())
            samples.append(
                {"path": _relative(project, file), "line": line + offset, "snippet": snippet}
            )
        if not dry_run:
            try:
                save_text(file, header + pattern.sub(replacement, body))
            except OSError as exc:
                raise SearchError(f"写入失败：{file}（{exc}）") from exc

    return {
        "dry_run": dry_run,
        "total": total,
        "files": len(changed),
        "changed": changed,
        "samples": samples[:12],
    }
