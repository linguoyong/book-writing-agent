"""运行中的应用异步补齐向量；保存文件本身不等待模型下载或外部 API。"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

_enabled = False
_pending: set[Path] = set()
_lock = threading.Lock()
_worker: threading.Thread | None = None
_log = logging.getLogger(__name__)


def enable_updates(enabled: bool) -> None:
    global _enabled
    with _lock:
        _enabled = enabled
        if not enabled:
            _pending.clear()


def queue_embeddings(project: Path) -> None:
    global _worker
    with _lock:
        if not _enabled:
            return
        _pending.add(project.resolve())
        if _worker is None:
            _worker = threading.Thread(target=_drain, daemon=True, name="index-updates")
            _worker.start()


def _drain() -> None:
    global _worker
    while True:
        with _lock:
            if not _enabled or not _pending:
                _worker = None
                return
            project = _pending.pop()
        try:
            from ..config import load_settings
            from .search import KbIndex

            settings = load_settings().embedding
            if project.exists() and settings.provider != "none":
                KbIndex(project, settings).embed_pending()
        except Exception:  # noqa: BLE001
            _log.exception("后台更新向量失败：%s", project.name)
