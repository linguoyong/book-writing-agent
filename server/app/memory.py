from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import MEMORY_DIR
from .text import read_text

SEED_USER = """# USER.md — 关于用户

> 跨项目的稳定偏好。越短越准，由用户或 Agent 维护。

## 基本信息
- 称呼：
- 职业/角色：
- 常用语言：中文

## 工作方式偏好
- 沟通：简洁、直接，先结论后展开
- 交付：结构化（表格 / 清单），标注文件路径与改动

## 长期关注
-
"""

SEED_LONG = """# MEMORY.md — 长期记忆

> 跨会话沉淀的事实、决策与经验。每条带日期；与旧记忆冲突时新增并标注，不静默覆盖。
"""

SCOPE_TITLES = {
    "user": "用户记忆",
    "long": "长期记忆",
    "project": "项目记忆",
}

_WS = re.compile(r"\s+")


def memory_path(scope: str, project: Path | None = None) -> Path:
    if scope == "user":
        return MEMORY_DIR / "USER.md"
    if scope == "long":
        return MEMORY_DIR / "MEMORY.md"
    if scope == "project":
        if project is None:
            raise ValueError("项目记忆需要 project 路径")
        return project / "AGENTS.md"
    raise ValueError(f"未知记忆范围: {scope}")


def ensure_files(project: Path | None = None) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    seeds = {"user": SEED_USER, "long": SEED_LONG}
    for scope, seed in seeds.items():
        file = memory_path(scope)
        if not file.exists():
            file.write_text(seed, encoding="utf-8")
    if project is not None:
        file = memory_path("project", project)
        if not file.exists():
            file.write_text(_seed_project(project), encoding="utf-8")


def _seed_project(project: Path) -> str:
    return (
        "# AGENTS.md — 项目记忆\n\n"
        "> 常驻本项目的上下文：写作约定、当前目标、不能碰的红线。"
        "Agent 可直接编辑本文件。\n\n"
        f"## 项目\n- 目录：{project.name}\n\n"
        "## 写作约定\n- 章节标题极简，不加副标题\n"
        "- 场景转换用 `---`，段落之间单空行\n"
        "- 禁用「不是 A，而是 B」句式\n\n"
        "## 当前目标\n-\n\n"
        "## 红线\n-\n"
    )


def set_project_words(project: Path, words: int) -> None:
    """把「每章目标字数」写进项目记忆的写作约定，供 Agent 每轮读取。"""
    file = memory_path("project", project)
    if not file.exists():
        return
    # Windows 下文件是 CRLF，先归一化再匹配
    text = read_text(file).replace("\r\n", "\n")
    line = f"- 每章目标约 {max(500, int(words or 5000))} 字"
    pattern = re.compile(r"^- 每章目标约 \d+ 字$", re.M)
    if pattern.search(text):
        text = pattern.sub(line, text, count=1)
    elif "## 写作约定" in text:
        text = text.replace("## 写作约定\n", f"## 写作约定\n{line}\n", 1)
    else:
        text = text.rstrip() + f"\n\n## 写作约定\n{line}\n"
    file.write_text(text, encoding="utf-8")


def read(scope: str, project: Path | None = None) -> str:
    file = memory_path(scope, project)
    if not file.exists():
        return ""
    return read_text(file)


def write(scope: str, content: str, project: Path | None = None) -> dict[str, Any]:
    file = memory_path(scope, project)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content.strip() + "\n", encoding="utf-8")
    return _describe(scope, file, project)


def append(scope: str, text: str, project: Path | None = None, source: str = "") -> str:
    """追加一条记忆；已存在相同内容时跳过。返回写入的行。"""
    text = text.strip()
    if not text:
        raise ValueError("记忆内容为空")
    file = memory_path(scope, project)
    file.parent.mkdir(parents=True, exist_ok=True)
    if not file.exists():
        ensure_files(project)
    existing = read_text(file)
    normalized = _WS.sub("", text)[:80]
    if normalized and normalized in _WS.sub("", existing):
        return ""

    suffix = f" <!-- src:{source} -->" if source else ""
    if scope == "long":
        _append_dated(file, existing, f"- {text}{suffix}")
    else:
        separator = "" if existing.endswith("\n") else "\n"
        file.write_text(f"{existing}{separator}- {text}{suffix}\n", encoding="utf-8")
    return text


def _append_dated(file: Path, existing: str, line: str) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    heading = f"## {today}"
    if heading in existing:
        head, _, tail = existing.partition(heading)
        # 插到该日期小节末尾（下一个 ## 之前）
        next_heading = tail.find("\n## ")
        if next_heading >= 0:
            body = tail[:next_heading].rstrip() + "\n" + line + "\n"
            rest = tail[next_heading:]
            file.write_text(f"{head}{heading}{body}{rest}", encoding="utf-8")
        else:
            file.write_text(f"{existing.rstrip()}\n{line}\n", encoding="utf-8")
        return
    file.write_text(f"{existing.rstrip()}\n\n{heading}\n{line}\n", encoding="utf-8")


def daily_log(text: str, project: Path | None = None, tag: str = "") -> None:
    """追加当日工作日志（只记录发生过的实质动作，不记录寒暄）。"""
    text = text.strip()
    if not text:
        return
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    file = MEMORY_DIR / f"{datetime.now():%Y-%m-%d}.md"
    stamp = datetime.now().strftime("%H:%M")
    prefix = f"[{tag}] " if tag else ""
    header = f"# {datetime.now():%Y-%m-%d}\n\n"
    body = read_text(file) if file.exists() else header
    file.write_text(f"{body.rstrip()}\n- {stamp} {prefix}{text}\n", encoding="utf-8")


def status(project: Path | None = None) -> list[dict[str, Any]]:
    ensure_files(project)
    scopes = [scope for scope in SCOPE_TITLES if scope != "project" or project is not None]
    items = [_describe(scope, memory_path(scope, project), project) for scope in scopes]
    logs = sorted(MEMORY_DIR.glob("20*.md"), reverse=True)[:5]
    items.append(
        {
            "scope": "daily",
            "title": "工作日志",
            "path": str(MEMORY_DIR),
            "chars": sum(len(read_text(f)) for f in logs),
            "updated": logs[0].stat().st_mtime if logs else 0,
            "files": [f.name for f in logs],
        }
    )
    return items


def _describe(scope: str, file: Path, project: Path | None) -> dict[str, Any]:
    text = read_text(file) if file.exists() else ""
    return {
        "scope": scope,
        "title": SCOPE_TITLES.get(scope, scope),
        "path": str(file),
        "chars": len(text),
        "updated": file.stat().st_mtime if file.exists() else 0,
    }


def distill_session(session_id: str, project: Path) -> dict[str, Any]:
    """把一段会话沉淀成长期记忆（3–6 条事实）。由用户显式触发。"""
    from . import db
    from .llm import build_chat_model

    messages = db.list_messages(session_id, limit=60)
    lines = [
        f"{'用户' if m['role'] == 'user' else '助手'}：{m['content'][:1200]}"
        for m in messages
        if m["content"].strip()
    ]
    if len(lines) < 2:
        return {"ok": False, "added": 0, "message": "会话内容太少，暂不沉淀"}

    prompt = (
        "从下面的写作对话中提炼长期有效的信息，输出 3-6 条 Markdown 列表项（以 - 开头）。\n"
        "只保留：作品设定决策、用户明确表达的偏好、已达成的结论、可复用的写作约束。\n"
        "不要记录寒暄、临时任务、模型自我介绍。若没有值得长期保留的信息，只输出：无。\n\n"
        + "\n".join(lines[-30:])
    )
    model = build_chat_model("extractor")
    result = model.invoke(prompt)
    text = result.content if isinstance(result.content, str) else str(result.content)
    items = [
        line.lstrip("-* ").strip()
        for line in text.splitlines()
        if line.strip().startswith(("-", "*")) and len(line.strip()) > 3
    ]
    added = 0
    for item in items[:6]:
        if item == "无":
            continue
        if append("long", item, source=f"session:{session_id}"):
            added += 1
    if added:
        daily_log(f"从会话 {session_id} 沉淀 {added} 条长期记忆", tag="memory")
    return {"ok": True, "added": added, "items": items[:6]}


_ENTRY_RE = re.compile(r"^-\s+(.*?)(?:\s*<!--\s*src:(.*?)\s*-->)?\s*$")


def entries(scope: str, project: Path | None = None) -> list[dict[str, str]]:
    """把记忆文件解析成条目（含日期与来源），供管理页展示。"""
    text = read(scope, project)
    items: list[dict[str, str]] = []
    current_date = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            candidate = stripped[3:].strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
                current_date = candidate
            continue
        match = _ENTRY_RE.match(stripped)
        if match:
            items.append(
                {
                    "text": match.group(1).strip(),
                    "date": current_date,
                    "source": (match.group(2) or "").strip(),
                }
            )
    return items


def delete_entry(scope: str, text: str, project: Path | None = None) -> bool:
    file = memory_path(scope, project)
    if not file.exists():
        return False
    target = _WS.sub("", text)[:80]
    if not target:
        return False

    lines = read_text(file).splitlines()
    kept: list[str] = []
    removed = False
    for line in lines:
        match = _ENTRY_RE.match(line.strip())
        if not removed and match and _WS.sub("", match.group(1))[:80] == target:
            removed = True
            continue
        kept.append(line)
    if not removed:
        return False

    cleaned: list[str] = []
    for index, line in enumerate(kept):
        stripped = line.strip()
        if re.fullmatch(r"## \d{4}-\d{2}-\d{2}", stripped):
            following = [item for item in kept[index + 1 :] if item.strip()]
            next_line = following[0].strip() if following else ""
            if not next_line.startswith("- "):
                continue
        cleaned.append(line)

    file.write_text("\n".join(cleaned).rstrip() + "\n", encoding="utf-8")
    return True
