"""工作区文本变更：同一项目内串行写入，维护审稿与检索的派生状态。"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any

from .text import normalize_newlines, read_text, save_text

_locks: dict[str, Any] = {}
_locks_guard = threading.Lock()
_policy: ContextVar[Any] = ContextVar("workspace_write_policy", default=None)
_log = logging.getLogger(__name__)


class FileConflictError(ValueError):
    """文件在编辑后被其他操作修改。"""


def project_lock(project: Path):
    key = str(project.resolve()).casefold()
    with _locks_guard:
        return _locks.setdefault(key, threading.RLock())


@contextmanager
def write_policy(sandbox: Any) -> Iterator[None]:
    token = _policy.set(sandbox)
    try:
        yield
    finally:
        _policy.reset(token)


def check_write(project: Path, target: Path) -> Path:
    from .config import load_settings
    from .sandbox import check_path

    target = target.resolve()
    relative = target.relative_to(project.resolve()).as_posix()
    sandbox = _policy.get()
    if sandbox is None:
        sandbox = load_settings().sandbox
    if check_path(sandbox, relative, "write") == "deny":
        raise PermissionError(f"路径规则禁止写入：{relative}")
    return target


def body_hash(body: str) -> str:
    return hashlib.sha256(normalize_newlines(body).strip().encode("utf-8")).hexdigest()


def invalidate_review(old: str, new: str) -> str:
    from .kb.repository import dump_note, parse_note

    old_meta, old_body = parse_note(old)
    meta, body = parse_note(new)
    old_review = old_meta.get("review")
    review = meta.get("review")
    if isinstance(old_review, dict):
        review = old_review
    if not isinstance(review, dict):
        return new
    # 允许仅改元数据；正文变化时无论工具是否保留原 front-matter 都必须失效。
    if body_hash(old_body) == body_hash(body):
        if isinstance(old_review, dict) and meta.get("review") != old_review:
            meta["review"] = dict(old_review)
            return dump_note(meta, body)
        return new
    meta = meta or {key: value for key, value in old_meta.items() if key != "review"}
    meta["review"] = {
        **review,
        "status": "stale",
        "stale_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    return dump_note(meta, body)


def refresh_source(project: Path, target: Path) -> None:
    """已有索引立即更新关键词和清除过期向量，向量编码放到后台。"""
    from .config import EmbeddingSettings
    from .kb.search import KbIndex, invalidate_entities
    from .kb.updates import queue_embeddings

    invalidate_entities(project)
    if not (project / ".index/search.db").exists():
        return
    relative = target.resolve().relative_to(project.resolve()).as_posix()
    try:
        KbIndex(project, EmbeddingSettings(provider="none")).reindex_source(relative)
        queue_embeddings(project)
    except Exception:  # noqa: BLE001 - 正文已保存，派生索引可重建
        _log.exception("更新索引失败：%s", relative)
        # 保留可发现的失败状态，下次重建成功后清除。
        save_text(project / ".index/needs-reindex", relative)


def write_project_text(
    project: Path,
    target: Path,
    content: str,
    *,
    expected_mtime: int | None = None,
    invalidate: bool = True,
) -> int:
    from .workspace import snapshot_file

    with project_lock(project):
        target = check_write(project, target)
        if expected_mtime is not None:
            if not target.exists() or abs(int(target.stat().st_mtime * 1000) - expected_mtime) > 2:
                raise FileConflictError("文件已被其他操作修改，请重新加载后再保存")
        old = read_text(target) if target.exists() else ""
        relative = target.relative_to(project.resolve()).parts
        if invalidate and relative[0] == "manuscript" and target.suffix.lower() == ".md":
            content = invalidate_review(old, content)
        if old != content or not target.exists():
            snapshot_file(project, target)
            save_text(target, content)
            refresh_source(project, target)
        return int(target.stat().st_mtime * 1000)
