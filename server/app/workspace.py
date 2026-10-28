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
