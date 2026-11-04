from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from .proc import run_hidden

HASH_RE = re.compile(r"^[0-9a-f]{7,40}$")


class VersionError(RuntimeError):
    """版本操作失败，消息可直接展示给用户。"""


def _git(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # run_hidden：windowed 后端拉起 git 会闪黑框
    return run_hidden(
        ["git", *args],
        cwd=project,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _check_hash(commit: str) -> str:
    commit = (commit or "").strip()
    if not HASH_RE.match(commit):
        raise VersionError(f"提交号不合法：{commit}")
    return commit


def _safe_path(project: Path, path: str) -> Path:
    relative = str(path or "").strip().lstrip("/").replace("\\", "/")
    if not relative or ".." in relative.split("/"):
        raise VersionError(f"路径不合法：{path}")
    target = (project / relative).resolve()
    root = project.resolve()
    if not str(target).startswith(str(root)):
        raise VersionError(f"路径越界：{path}")
    return target


def log(project: Path, limit: int = 40) -> list[dict[str, Any]]:
    if not (project / ".git").exists():
        return []
    result = _git(
        project,
        "log",
        f"-n{max(1, min(limit, 200))}",
        "--pretty=format:%H%x1f%h%x1f%an%x1f%ad%x1f%s",
        "--date=format:%Y-%m-%d %H:%M",
    )
    if result.returncode != 0:
        return []
    commits: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) < 5:
            continue
        commits.append(
            {
                "hash": parts[0],
                "short": parts[1],
                "author": parts[2],
                "date": parts[3],
                "message": parts[4],
            }
        )
    return commits


def files(project: Path, commit: str) -> list[dict[str, str]]:
    commit = _check_hash(commit)
    result = _git(project, "show", "--name-status", "--format=", commit)
    if result.returncode != 0:
        raise VersionError(f"读取提交失败：{result.stderr.strip()[:200]}")
    items: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        items.append({"status": parts[0][:1], "path": parts[-1]})
    return items


def file_diff(project: Path, commit: str, path: str) -> dict[str, Any]:
    commit = _check_hash(commit)
    _safe_path(project, path)
    result = _git(project, "show", "--format=", commit, "--", path)
    if result.returncode != 0:
        raise VersionError(f"读取 diff 失败：{result.stderr.strip()[:200]}")
    return {"path": path, "diff": result.stdout}


def read_file_at(project: Path, commit: str, path: str) -> dict[str, Any]:
    commit = _check_hash(commit)
    _safe_path(project, path)
    result = _git(project, "show", f"{commit}:{path}")
    if result.returncode != 0:
        raise VersionError(f"该提交里没有这个文件：{path}")
    return {"path": path, "content": result.stdout}


def _read_blob(project: Path, commit: str, path: str) -> bytes:
    """按原始字节取出某个提交里的文件，避免 Windows 换行转换把内容改掉。"""
    result = run_hidden(
        ["git", "show", f"{commit}:{path}"],
        cwd=project,
        capture_output=True,
    )
    if result.returncode != 0:
        raise VersionError(f"该提交里没有这个文件：{path}")
    return result.stdout


def restore(project: Path, commit: str, path: str) -> dict[str, Any]:
    """把单个文件恢复到某个提交，并提交这次恢复（不改写历史）。"""
    commit = _check_hash(commit)
    target = _safe_path(project, path)
    data = _read_blob(project, commit, path)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as exc:
        raise VersionError(f"写入失败：{exc}") from exc

    changed = _git(project, "status", "--porcelain", "--", path).stdout.strip()
    if not changed:
        # 内容已经和该版本一致，没有可提交的改动，按成功处理
        head = _git(project, "rev-parse", "--short", "HEAD").stdout.strip()
        return {"path": path, "commit": head, "restored_from": commit[:7], "unchanged": True}

    _git(project, "add", "--", path)
    result = _git(project, "commit", "-m", f"恢复 {path} 到 {commit[:7]}")
    if result.returncode != 0:
        raise VersionError(f"提交失败：{result.stderr.strip()[:200]}")

    head = _git(project, "rev-parse", "--short", "HEAD").stdout.strip()
    return {"path": path, "commit": head, "restored_from": commit[:7], "unchanged": False}


def commit_all(project: Path, message: str = "") -> dict[str, Any]:
    """把当前改动提交掉，返回新提交号；没有改动时返回 None。"""
    status = _git(project, "status", "--porcelain").stdout.strip()
    if not status:
        return {"commit": None, "changed": 0}
    _git(project, "add", "-A")
    text = message.strip() or "保存当前进度"
    result = _git(project, "commit", "-m", text)
    if result.returncode != 0:
        raise VersionError(f"提交失败：{result.stderr.strip()[:200]}")
    head = _git(project, "rev-parse", "--short", "HEAD").stdout.strip()
    return {"commit": head, "changed": len(status.splitlines())}
