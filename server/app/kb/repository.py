from __future__ import annotations

import re
from datetime import UTC
from pathlib import Path
from typing import Any

import yaml

from ..text import normalize_newlines, read_text

KINDS = [
    "characters",
    "factions",
    "items",
    "locations",
    "world",
    "outline",
    "materials",
    "styles",
]

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)
_SAFE_ID = re.compile(r"[^\w\u4e00-\u9fff-]+")


def kind_dir(project: Path, kind: str) -> Path:
    if kind not in KINDS:
        raise ValueError(f"未知知识库类型: {kind}")
    return project / "kb" / kind


def safe_entity_id(entity_id: str) -> str:
    cleaned = _SAFE_ID.sub("-", entity_id.strip()).strip("-")
    if not cleaned:
        raise ValueError("实体 id 不能为空")
    return cleaned


def parse_note(text: str) -> tuple[dict[str, Any], str]:
    text = normalize_newlines(text)
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        # 首尾两行 --- 之间不是合法 YAML（常见于正文首行就是场景分隔线），
        # 这时整份内容都算正文，不能把第一段当 front-matter 吃掉。
        return {}, text
    if not isinstance(meta, dict) or not meta:
        return {}, text
    return meta, match.group(2)


def dump_note(meta: dict[str, Any], body: str) -> str:
    header = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{header}\n---\n\n{normalize_newlines(body).strip()}\n"


def entity_file(project: Path, kind: str, entity_id: str) -> Path:
    return kind_dir(project, kind) / f"{safe_entity_id(entity_id)}.md"


def list_entities(project: Path, kind: str) -> list[dict[str, Any]]:
    directory = kind_dir(project, kind)
    if not directory.exists():
        return []
    items: list[dict[str, Any]] = []
    for file in sorted(directory.glob("*.md")):
        meta, body = parse_note(read_text(file))
        items.append(
            {
                "id": meta.get("id") or file.stem,
                "kind": kind,
                "title": _display_title(meta, file.stem),
                "meta": meta,
                "body": body,
                "file": str(file.relative_to(project)),
                "updated_at": file.stat().st_mtime,
            }
        )
    return items


def get_entity(project: Path, kind: str, entity_id: str) -> dict[str, Any] | None:
    file = entity_file(project, kind, entity_id)
    if not file.exists():
        return None
    meta, body = parse_note(read_text(file))
    return {
        "id": meta.get("id") or file.stem,
        "kind": kind,
        "title": _display_title(meta, file.stem),
        "meta": meta,
        "body": body,
        "file": str(file.relative_to(project)),
    }


def save_entity(
    project: Path, kind: str, entity_id: str, meta: dict[str, Any], body: str
) -> dict[str, Any]:
    entity_id = safe_entity_id(entity_id)
    directory = kind_dir(project, kind)
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / f"{entity_id}.md"

    merged_meta = dict(meta or {})
    merged_meta["id"] = entity_id
    merged_meta.setdefault("type", kind[:-1] if kind.endswith("s") else kind)
    merged_meta["updated_at"] = _now()

    from ..fileops import write_project_text

    write_project_text(project, file, dump_note(merged_meta, body))
    saved = get_entity(project, kind, entity_id)
    assert saved is not None
    return saved


def delete_entity(project: Path, kind: str, entity_id: str) -> bool:
    file = entity_file(project, kind, entity_id)
    if file.exists():
        file.unlink()
        return True
    return False


def _display_title(meta: dict[str, Any], fallback: str) -> str:
    for key in ("name", "title"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()


def state_at(meta: dict[str, Any], chapter: int) -> dict[str, Any] | None:
    """取第 N 章时点上的角色状态（timeline 里 chapter <= N 的最后一条）。"""
    timeline = meta.get("timeline") if isinstance(meta, dict) else None
    if not isinstance(timeline, list) or not timeline:
        return None
    applicable = []
    for entry in timeline:
        if not isinstance(entry, dict):
            continue
        try:
            number = int(entry.get("chapter") or 0)
        except (TypeError, ValueError):
            number = 0
        if number <= chapter:
            applicable.append((number, entry))
    if not applicable:
        return None
    number, entry = max(applicable, key=lambda item: item[0])
    return {"chapter": number, "state": entry.get("state") or {}}


def trim_meta(meta: dict[str, Any], chapter: int) -> dict[str, Any]:
    """把 timeline 裁到当前进度，避免模型读到后面的状态（防剧透）。"""
    timeline = meta.get("timeline")
    if not chapter or not isinstance(timeline, list) or not timeline:
        return meta
    kept = []
    for entry in timeline:
        if not isinstance(entry, dict):
            continue
        try:
            number = int(entry.get("chapter") or 0)
        except (TypeError, ValueError):
            number = 0
        if number <= chapter:
            kept.append(entry)
    trimmed = dict(meta)
    trimmed["timeline"] = kept[-3:]
    return trimmed
