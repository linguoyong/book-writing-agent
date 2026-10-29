from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .kb.repository import dump_note, parse_note, safe_entity_id
from .text import read_text

DEFAULT_EXPERTS: list[dict[str, Any]] = [
    {
        "id": "general",
        "name": "通用编辑",
        "description": "不额外约束风格，按你的要求写作、修改与整理",
        "tags": ["通用", "编辑"],
        "avatar": "通",
        "prompt": "",
        "skills": [],
        "body": "## 工作方式\n- 先确认目标与当前进度\n- 涉及设定时先检索知识库\n- 改完正文提示保存并查看变更",
    },
    {
        "id": "cold-narrative",
        "name": "冷峻叙事者",
        "description": "短句、克制、少形容词，情绪藏在动作里",
        "tags": ["风格", "冷硬"],
        "avatar": "冷",
        "prompt": "冷峻克制的第三人称叙事，短句为主，少用形容词，情绪藏在动作里",
        "skills": [],
        "body": "## 写作方法\n- 每段只推进一个动作或一个信息\n- 删除解释性副词，让对白与动作承担情绪\n- 章末留一个未解释的画面",
    },
    {
        "id": "lyrical",
        "name": "细腻抒情者",
        "description": "重视感官与心理描写，节奏舒缓",
        "tags": ["风格", "抒情"],
        "avatar": "抒",
        "prompt": "细腻抒情的叙事，注重感官与心理描写，节奏舒缓",
        "skills": [],
        "body": "## 写作方法\n- 用五感建立场景，再进入人物内心\n- 长句与短句交替，避免整段同长度\n- 抒情必须落在具体物象上，不空写情绪",
    },
    {
        "id": "fast-pace",
        "name": "快节奏写手",
        "description": "冲突密集，段落短，章末留钩子",
        "tags": ["风格", "爽文"],
        "avatar": "快",
        "prompt": "快节奏爽文风格，冲突密集，段落短，章末留钩子",
        "skills": [],
        "body": "## 写作方法\n- 开篇 200 字内出现冲突或目标\n- 每 800 字一个小转折\n- 章末抛出问题或威胁，不总结",
    },
    {
        "id": "classical",
        "name": "古典雅致者",
        "description": "白话为骨、文言为韵，句式整饬",
        "tags": ["风格", "古典"],
        "avatar": "古",
        "prompt": "古典雅致的白话文风，用词典雅，句式整饬",
        "skills": [],
        "body": "## 写作方法\n- 以白话为主，适度使用四字结构与古语词\n- 称谓、器物、礼制必须与世界观一致\n- 避免现代口语与翻译腔",
    },
    {
        "id": "suspense",
        "name": "悬疑冷调者",
        "description": "信息克制，氛围压迫，善用留白",
        "tags": ["风格", "悬疑"],
        "avatar": "悬",
        "prompt": "悬疑冷调叙事，信息克制，氛围压迫，善用留白",
        "skills": [],
        "body": "## 写作方法\n- 每章只给一条新线索，同时隐藏一条旧线索\n- 用环境细节制造不安，不直接解释\n- 对白留半句，让读者自己补全",
    },
]


def expert_dir(project: Path) -> Path:
    directory = project / "experts"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def seed_experts(project: Path) -> None:
    directory = expert_dir(project)
    if any(directory.glob("*.md")):
        return
    for item in DEFAULT_EXPERTS:
        save_expert(
            project,
            item["id"],
            {
                "name": item["name"],
                "description": item["description"],
                "tags": item["tags"],
                "avatar": item["avatar"],
                "prompt": item["prompt"],
                "skills": item["skills"],
            },
            item["body"],
        )


def list_experts(project: Path) -> list[dict[str, Any]]:
    seed_experts(project)
    items: list[dict[str, Any]] = []
    for file in sorted(expert_dir(project).glob("*.md")):
        meta, body = parse_note(read_text(file))
        items.append(_to_expert(meta, body, file, project))
    return items


def get_expert(project: Path, expert_id: str) -> dict[str, Any] | None:
    seed_experts(project)
    file = expert_dir(project) / f"{safe_entity_id(expert_id)}.md"
    if not file.exists():
        return None
    meta, body = parse_note(read_text(file))
    return _to_expert(meta, body, file, project)


def save_expert(
    project: Path, expert_id: str, meta: dict[str, Any], body: str = ""
) -> dict[str, Any]:
    expert_id = safe_entity_id(expert_id)
    directory = expert_dir(project)
    meta = dict(meta or {})
    meta["id"] = expert_id
    meta.setdefault("name", expert_id)
    meta.setdefault("description", "")
    meta.setdefault("tags", [])
    meta.setdefault("avatar", str(meta["name"])[:1])
    meta.setdefault("prompt", "")
    meta.setdefault("skills", [])
    meta.setdefault("max_turns", 50)
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    (directory / f"{expert_id}.md").write_text(dump_note(meta, body), encoding="utf-8")
    saved = get_expert(project, expert_id)
    assert saved is not None
    return saved


def delete_expert(project: Path, expert_id: str) -> bool:
    file = expert_dir(project) / f"{safe_entity_id(expert_id)}.md"
    if file.exists():
        file.unlink()
        return True
    return False


def _to_expert(meta: dict[str, Any], body: str, file: Path, project: Path) -> dict[str, Any]:
    return {
        "id": meta.get("id") or file.stem,
        "name": meta.get("name") or file.stem,
        "description": meta.get("description") or "",
        "tags": meta.get("tags") or [],
        "avatar": meta.get("avatar") or str(meta.get("name") or file.stem)[:1],
        "prompt": meta.get("prompt") or "",
        "skills": meta.get("skills") or [],
        "max_turns": int(meta.get("max_turns") or 50),
        "body": body,
        "file": str(file.relative_to(project)),
    }
