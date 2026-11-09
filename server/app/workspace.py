from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import BOOKS_DIR, load_settings
from .proc import run_hidden
from .sandbox import check_path
from .text import read_text, save_text

# 写入前的旧版本留在这里：`.index/` 已在书稿 .gitignore 里，不进版本库，
# 但被误覆盖时能从磁盘直接捞回来。
HISTORY_DIR = ".index/history"
HISTORY_KEEP = 20

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
    # 每章目标字数：写作时用于篇幅提示与节奏检查
    "words_per_chapter": 5000,
    "created_with": "book-writing-agent",
}


def slugify(name: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name.strip()).strip("-").lower()
    return cleaned or "book"


def init_book_dir(path: Path, title: str, author: str = "", words_per_chapter: int = 5000) -> Path:
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
        data["words_per_chapter"] = max(500, int(words_per_chapter or 5000))
        save_text(book_file, json.dumps(data, ensure_ascii=False, indent=2))
    else:
        # 旧书稿补齐新字段，不改动已有设置
        try:
            data = json.loads(book_file.read_text(encoding="utf-8"))
            if "words_per_chapter" not in data:
                data["words_per_chapter"] = 5000
                save_text(book_file, json.dumps(data, ensure_ascii=False, indent=2))
            words_per_chapter = int(data.get("words_per_chapter") or words_per_chapter)
        except json.JSONDecodeError:
            pass

    # 目标字数落到项目记忆，Agent 每轮都能读到
    memory.set_project_words(path, words_per_chapter)

    if not (path / ".gitignore").exists():
        save_text(path / ".gitignore", ".index/\n*.tmp\n.tmp-*.tmp\n")
    # 书稿由应用按 LF 写盘；不声明的话 autocrlf 会把工作区转成 CRLF，
    # 内容没变也会一直显示「已修改」。
    if not (path / ".gitattributes").exists():
        save_text(path / ".gitattributes", "* text=auto eol=lf\n")

    if not (path / ".git").exists():
        _git(path, "init")

    _ensure_initial_commit(path)
    return path


def snapshot_file(project: Path, file: Path, keep: int = HISTORY_KEEP) -> None:
    """覆盖前把旧内容复制到 `.index/history/<相对路径>/<时间戳>.md`。

    书稿是唯一不可重建的数据。原子写能防「写一半被杀」，但防不了
    「模型把整章覆盖成别的内容」；这里留一份本地快照，不打扰 git 历史。
    """
    try:
        if not file.exists() or file.stat().st_size == 0:
            return
        relative = file.resolve().relative_to(project.resolve())
    except (OSError, ValueError):
        return
    history = project / HISTORY_DIR / relative.parent / relative.stem
    try:
        history.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(file, history / f"{stamp}{file.suffix}")
        _prune_history(history, keep)
    except OSError:
        # 快照失败不该阻塞写入本身
        return


def _prune_history(directory: Path, keep: int) -> None:
    try:
        files = sorted(directory.iterdir(), key=lambda item: item.name)
    except OSError:
        return
    for old in files[:-keep] if keep > 0 else files:
        try:
            old.unlink()
        except OSError:
            continue


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        # run_hidden：安装包里的后端是 windowed 程序，直接 subprocess.run 会闪黑框
        return run_hidden(
            ["git", *args],
            cwd=str(path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        # 宁可少一段 diff，也不要让整个请求（甚至事件循环）挂住
        return subprocess.CompletedProcess(["git", *args], 1, "", "git 命令超时")
    except OSError as exc:
        # 目标机器没装 git：版本功能整体降级，不要因此让整个接口 500。
        # stderr 里带上原因，前端「版本」页会把它当成「未启用」而不是「出错」。
        return subprocess.CompletedProcess(["git", *args], 1, "", f"git 不可用：{exc}")


def _ensure_initial_commit(path: Path) -> None:
    if not (path / ".git").exists():
        return
    status = _git(path, "status", "--porcelain")
    if status.stdout.strip():
        _git(path, "add", "-A")
        _git(path, "commit", "-m", "初始化书稿项目")


def create_book(
    name: str,
    title: str = "",
    author: str = "",
    target_dir: str = "",
    words_per_chapter: int = 5000,
) -> Path:
    if target_dir:
        path = Path(target_dir).expanduser().resolve()
    else:
        path = (BOOKS_DIR / slugify(name)).resolve()
    return init_book_dir(path, title or name, author, words_per_chapter)


def read_book_meta(path: Path) -> dict[str, Any]:
    book_file = path / "book.json"
    if not book_file.exists():
        return dict(DEFAULT_BOOK)
    try:
        raw = json.loads(book_file.read_text(encoding="utf-8"))
        return {**DEFAULT_BOOK, **raw}
    except json.JSONDecodeError:
        return dict(DEFAULT_BOOK)


def write_book_meta(path: Path, data: dict[str, Any]) -> None:
    snapshot_file(path, path / "book.json")
    save_text(path / "book.json", json.dumps(data, ensure_ascii=False, indent=2))


def git_status(path: Path) -> str:
    if not (path / ".git").exists():
        return "not-a-repository"
    return _git(path, "status", "--porcelain").stdout


def git_diff(path: Path, relative: str | None = None) -> str:
    """未提交改动。

    - `relative` 为空：返回全部改动（工作区 + 暂存区）与未跟踪文件；
    - `relative` 指定文件：只返回该文件的 diff（未跟踪按新文件生成）。
      单文件使用超大上下文（整文件进 diff），前端按「N unmodified lines」
      折叠未修改区域，与 IDE 的变更视图一致。
    """
    if not (path / ".git").exists():
        return ""

    # 变更面板与模型上下文共用同一条读边界：.env / 私钥不该出现在 diff 里
    sandbox = load_settings().sandbox

    if relative:
        normalized = relative.replace("\\", "/")
        if check_path(sandbox, normalized, "read") == "deny":
            return ""
        try:
            target = safe_join(path, normalized)
        except ValueError:
            return ""
        tracked = _git(path, "ls-files", "--", normalized).stdout.strip()
        if tracked:
            diff = _git(
                path,
                "-c",
                "core.quotepath=false",
                "diff",
                "-U1000000",
                "HEAD",
                "--",
                normalized,
            ).stdout
            if not diff.strip():
                diff = _git(
                    path,
                    "-c",
                    "core.quotepath=false",
                    "diff",
                    "-U1000000",
                    "--",
                    normalized,
                ).stdout
            return diff
        if target.is_file():
            return _new_file_diff(target, normalized)
        return ""

    tracked = _git(path, "-c", "core.quotepath=false", "diff", "HEAD", "--", ".").stdout
    if not tracked.strip():
        tracked = _git(path, "-c", "core.quotepath=false", "diff", "--", ".").stdout

    parts: list[str] = [tracked.strip()] if tracked.strip() else []
    untracked = _git(
        path, "-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard"
    ).stdout
    for line in untracked.splitlines():
        relative_path = line.strip()
        if not relative_path:
            continue
        if check_path(sandbox, relative_path.replace("\\", "/"), "read") == "deny":
            continue
        try:
            target = safe_join(path, relative_path)
        except ValueError:
            continue
        if not target.is_file():
            continue
        diff = _new_file_diff(target, relative_path)
        if diff.strip():
            parts.append(diff)
    return "\n".join(parts)


def git_commit(path: Path, message: str) -> tuple[bool, str]:
    """把工作区全部改动提交到本地仓库，返回 (是否成功, 输出)。"""
    if not (path / ".git").exists():
        return False, "当前工作区不是 git 仓库"
    staged = _git(path, "add", "-A")
    if staged.returncode != 0:
        return False, (staged.stderr or staged.stdout).strip()[:500] or "git add 失败"
    commit = _git(
        path,
        "-c",
        "user.name=写作 Agent",
        "-c",
        "user.email=book@local",
        "commit",
        "-m",
        message,
    )
    output = (commit.stdout + commit.stderr).strip()
    if commit.returncode != 0:
        if "nothing to commit" in output or "无文件要提交" in output:
            return False, "没有需要提交的改动"
        return False, output[:500] or "提交失败"
    return True, output[:500]


def git_status_map(path: Path) -> dict[str, str]:
    """porcelain 状态 → {相对路径: untracked|added|modified|deleted}。"""
    text = _git(path, "-c", "core.quotepath=false", "status", "--porcelain", "-uall").stdout
    result: dict[str, str] = {}
    for line in text.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        name = line[3:].strip()
        if " -> " in name:
            name = name.split(" -> ", 1)[1]
        if code == "??":
            state = "untracked"
        elif "D" in code:
            state = "deleted"
        elif "A" in code:
            state = "added"
        else:
            state = "modified"
        result[name.replace("\\", "/")] = state
    return result


def git_changes(path: Path) -> list[dict[str, Any]]:
    """已更改文件列表：状态 + 增删行数，供变更视图的文件树使用。"""
    if not (path / ".git").exists():
        return []
    states = git_status_map(path)
    numstat = _git(
        path, "-c", "core.quotepath=false", "diff", "--numstat", "HEAD", "--", "."
    ).stdout
    stats: dict[str, tuple[int, int]] = {}
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted, name = parts[0], parts[1], parts[2]
        stats[name.replace("\\", "/")] = (
            int(added) if added.isdigit() else 0,
            int(deleted) if deleted.isdigit() else 0,
        )

    items: list[dict[str, Any]] = []
    for name, state in states.items():
        additions, deletions = stats.get(name, (0, 0))
        if state == "untracked":
            target = safe_join(path, name) if name else None
            if target and target.is_file():
                try:
                    additions = len(read_text(target).splitlines())
                except OSError:
                    additions = 0
        items.append(
            {
                "path": name,
                "status": state,
                "additions": additions,
                "deletions": deletions,
            }
        )
    items.sort(key=lambda item: item["path"])
    return items


def safe_join(root: Path, relative: str) -> Path:
    """把工作区相对路径解析成绝对路径，越界（含兄弟目录前缀伪装）一律拒绝。

    不能用字符串 startswith：`/books/proj` 与 `/books/proj-evil` 前缀相同，
    拼接 `../proj-evil/x` 后会绕过检查。这里按路径层级判断，并已解析符号链接。
    """
    base = root.resolve()
    candidate = (base / relative).resolve()
    if candidate != base and base not in candidate.parents:
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
            diff = _git(project, "-c", "core.quotepath=false", "diff", "--", relative).stdout
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
        content = read_text(target)
    except OSError:
        return ""
    lines = content.splitlines()[:400]
    header = [
        f"diff --git a/{relative} b/{relative}",
        "new file mode 100644",
        "--- /dev/null",
        f"+++ b/{relative}",
        f"@@ -0,0 +1,{len(lines)} @@",
    ]
    return "\n".join([*header, *[f"+{line}" for line in lines]])
