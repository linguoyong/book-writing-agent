from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .config import BOOKS_DIR

KB_DIRS = {
    "characters": "characters",
    "factions": "factions",
    "items": "items",
    "locations": "locations",
    "world": "world",
    "outline": "outline",
    "materials": "materials",
    "styles": "styles",
}

DEFAULT_BOOK = {
    "title": "",
    "author": "",
    "synopsis": "",
    "progress": {"volume": 1, "chapter": 1},
    "created_with": "book-writing-agent",
}


def slugify(name: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name.strip()).strip("-").lower()
    return cleaned or "book"


def init_book_dir(path: Path, title: str, author: str = "") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "manuscript").mkdir(exist_ok=True)
    (path / "chapters").mkdir(exist_ok=True)
    (path / ".index").mkdir(exist_ok=True)
    for sub in KB_DIRS.values():
        (path / "kb" / sub).mkdir(parents=True, exist_ok=True)
    (path / "skills").mkdir(exist_ok=True)
    (path / "experts").mkdir(exist_ok=True)

    from . import memory
    from .experts import seed_experts

    memory.ensure_files(path)
    seed_experts(path)

    book_file = path / "book.json"
    if not book_file.exists():
        data = dict(DEFAULT_BOOK)
        data["title"] = title
        data["author"] = author
        book_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    if not (path / ".gitignore").exists():
        (path / ".gitignore").write_text(".index/\n*.tmp\n", encoding="utf-8")

    if not (path / ".git").exists():
        _git(path, "init")

    _ensure_initial_commit(path)
    return path


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _ensure_initial_commit(path: Path) -> None:
    if not (path / ".git").exists():
        return
    status = _git(path, "status", "--porcelain")
    if status.stdout.strip():
        _git(path, "add", "-A")
        _git(path, "commit", "-m", "初始化书稿项目")


def create_book(name: str, title: str = "", author: str = "", target_dir: str = "") -> Path:
    if target_dir:
        path = Path(target_dir).expanduser().resolve()
    else:
        path = (BOOKS_DIR / slugify(name)).resolve()
    return init_book_dir(path, title or name, author)


def read_book_meta(path: Path) -> dict[str, Any]:
    book_file = path / "book.json"
    if not book_file.exists():
        return dict(DEFAULT_BOOK)
    try:
        return json.loads(book_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(DEFAULT_BOOK)


def write_book_meta(path: Path, data: dict[str, Any]) -> None:
    (path / "book.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def git_status(path: Path) -> str:
    if not (path / ".git").exists():
        return "not-a-repository"
    return _git(path, "status", "--porcelain").stdout


def git_diff(path: Path) -> str:
    if not (path / ".git").exists():
        return ""
    return _git(path, "diff", "--", ".").stdout


def safe_join(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not str(candidate).startswith(str(root.resolve())):
        raise ValueError("路径越界")
    return candidate


def default_project_path(name: str) -> Path:
    return (BOOKS_DIR / slugify(name)).resolve()


def turn_changes(project: Path, paths: list[str], limit: int = 20000) -> dict[str, Any]:
    """本轮写过的文件相对 HEAD 的 diff，用于对话里的「查看变更」。"""
    unique = list(dict.fromkeys(path for path in paths if path))
    if not unique:
        return {"files": [], "diff": "", "truncated": False}
    if not (project / ".git").exists():
        return {"files": [], "diff": "", "truncated": False}

    tracked = _git(project, "-c", "core.quotepath=false", "ls-files", "--", *unique).stdout
    tracked_set = {line.strip() for line in tracked.splitlines() if line.strip()}

    files: list[str] = []
    chunks: list[str] = []
    seen: set[str] = set()
    for relative in unique:
        normalized = relative
        candidate = Path(relative)
        if candidate.is_absolute():
            try:
                normalized = str(candidate.resolve().relative_to(project.resolve())).replace(
                    "\\", "/"
                )
            except ValueError:
                continue
        if normalized in seen:
            continue
        try:
            target = safe_join(project, normalized)
        except ValueError:
            continue
        if not target.exists():
            continue
        seen.add(normalized)
        relative = normalized
        files.append(relative)
        if relative in tracked_set:
            diff = _git(
                project, "-c", "core.quotepath=false", "diff", "--", relative
            ).stdout
            if not diff.strip():
                diff = _git(
                    project, "-c", "core.quotepath=false", "diff", "--cached", "--", relative
                ).stdout
        else:
            diff = _new_file_diff(target, relative)
        if diff.strip():
            chunks.append(diff.strip())

    text = "\n".join(chunks)
    truncated = len(text) > limit
    if truncated:
        text = text[:limit].rstrip() + "\n…（diff 过长，已截断）"
    return {"files": files, "diff": text, "truncated": truncated}


def _new_file_diff(target: Path, relative: str) -> str:
    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    lines = content.splitlines()[:400]
    header = [
        "diff --git a/{0} b/{0}".format(relative),
        "new file mode 100644",
        "--- /dev/null",
        "+++ b/{}".format(relative),
        "@@ -0,0 +1,{} @@".format(len(lines)),
    ]
    return "\n".join([*header, *[f"+{line}" for line in lines]])
