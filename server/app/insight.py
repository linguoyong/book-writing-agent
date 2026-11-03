from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .db import now_iso
from .kb.repository import (
    KINDS,
    entity_file,
    list_entities,
    parse_note,
    safe_entity_id,
    save_entity,
)
from .text import read_text

# 关系图只画「有实体感」的几类，世界/大纲/素材/文风不进图
GRAPH_KINDS = ("characters", "factions", "locations", "items")
MAX_NODES = 160
MAX_MENTIONS_PER_NODE = 4
MIN_NAME_LEN = 2

_CHAPTER_RE = re.compile(r"第\s*(\d+)\s*章")
_CHAPTER_PREFIX_RE = re.compile(r"^第\s*\d+\s*章[\s:：·、\-—]*")
_YEAR_RE = re.compile(r"第\s*(\d+)\s*年")


class MaterialError(RuntimeError):
    """素材入库失败，消息可直接展示给用户。"""


# ---------------------------------------------------------------- 关系图


def _aliases(entity: dict[str, Any]) -> list[str]:
    meta = entity.get("meta") or {}
    raw = meta.get("aliases")
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _names(entity: dict[str, Any]) -> list[str]:
    names = [str(entity.get("title") or entity.get("id") or "")]
    names.extend(_aliases(entity))
    names.append(str(entity.get("id") or ""))
    result: list[str] = []
    for name in names:
        cleaned = name.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _relations_of(entity: dict[str, Any]) -> list[dict[str, str]]:
    """meta.relations 支持 [{target, label}] 与 "目标:标签" 两种写法。"""
    meta = entity.get("meta") or {}
    raw = meta.get("relations")
    if not raw:
        return []
    items: list[dict[str, str]] = []
    if isinstance(raw, str):
        raw = [line for line in raw.splitlines() if line.strip()]
    if not isinstance(raw, list):
        return []
    for entry in raw:
        if isinstance(entry, dict):
            target = str(entry.get("target") or entry.get("name") or "").strip()
            label = str(entry.get("label") or entry.get("type") or "关联").strip()
        else:
            text = str(entry).strip()
            if ":" in text:
                target, label = text.split(":", 1)
            elif "：" in text:
                target, label = text.split("：", 1)
            else:
                target, label = text, "关联"
            target, label = target.strip(), label.strip() or "关联"
        if target:
            items.append({"target": target, "label": label})
    return items


def collect_graph(
    project: Path,
    kinds: list[str] | None = None,
    include_mentions: bool = True,
) -> dict[str, Any]:
    """把卡片和它们之间的关系拼成一张图。

    - 显式关系：`meta.relations`（Agent 抽取或用户手写）
    - 自动关系：某张卡正文里提到了另一个实体的名字，记为「提及」（可关）
    """
    selected = [kind for kind in (kinds or GRAPH_KINDS) if kind in GRAPH_KINDS] or list(GRAPH_KINDS)
    entities: list[dict[str, Any]] = []
    for kind in selected:
        for entity in list_entities(project, kind):
            entities.append({**entity, "kind": kind})
    entities = entities[:MAX_NODES]

    nodes: list[dict[str, Any]] = []
    lookup: dict[str, str] = {}
    for entity in entities:
        node_id = f"{entity['kind']}/{entity['id']}"
        nodes.append(
            {
                "id": node_id,
                "entity_id": str(entity["id"]),
                "kind": entity["kind"],
                "name": str(entity.get("title") or entity["id"]),
                "aliases": _aliases(entity),
                "path": str(entity.get("file") or ""),
            }
        )
        for name in _names(entity):
            lookup.setdefault(name.lower(), node_id)

    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_edge(source: str, target: str, label: str, kind: str) -> None:
        if source == target:
            return
        # 关系是无向的：A→B 与 B→A 同标签只留一条，否则图上会出现两条平行线
        if kind == "relation" and (target, source, label) in edges:
            edges[(target, source, label)]["weight"] += 1
            return
        key = (source, target, label)
        if key in edges:
            edges[key]["weight"] += 1
            return
        edges[key] = {
            "source": source,
            "target": target,
            "label": label,
            "type": kind,
            "weight": 1,
        }

    unresolved: list[dict[str, str]] = []
    for entity in entities:
        node_id = f"{entity['kind']}/{entity['id']}"
        for relation in _relations_of(entity):
            target = lookup.get(relation["target"].lower())
            if not target:
                unresolved.append({"source": node_id, "target": relation["target"]})
                continue
            add_edge(node_id, target, relation["label"], "relation")

    mentions = 0
    if include_mentions:
        for entity in entities:
            node_id = f"{entity['kind']}/{entity['id']}"
            body = str(entity.get("body") or "")
            if not body:
                continue
            hits: list[tuple[int, str, str]] = []
            for other in nodes:
                if other["id"] == node_id:
                    continue
                count = 0
                for name in [other["name"], *other["aliases"]]:
                    if len(name) < MIN_NAME_LEN or name == entity.get("title"):
                        continue
                    count += body.count(name)
                if count:
                    hits.append((count, other["id"], other["name"]))
            hits.sort(reverse=True)
            for _count, target, _name in hits[:MAX_MENTIONS_PER_NODE]:
                add_edge(node_id, target, "提及", "mention")
                mentions += 1

    degree: dict[str, int] = {node["id"]: 0 for node in nodes}
    for edge in edges.values():
        degree[edge["source"]] = degree.get(edge["source"], 0) + 1
        degree[edge["target"]] = degree.get(edge["target"], 0) + 1
    for node in nodes:
        node["degree"] = degree.get(node["id"], 0)

    return {
        "nodes": nodes,
        "edges": list(edges.values()),
        "unresolved": unresolved[:30],
        "stats": {
            "nodes": len(nodes),
            "relations": sum(1 for edge in edges.values() if edge["type"] == "relation"),
            "mentions": sum(1 for edge in edges.values() if edge["type"] == "mention"),
            "isolated": sum(1 for node in nodes if node["degree"] == 0),
            "unresolved": len(unresolved),
        },
    }


# ---------------------------------------------------------------- 时间线


def _entry_of(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, str):
        text = raw.strip()
        return {"text": text} if text else None
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("state") or raw.get("event") or raw.get("text") or "").strip()
    if not text:
        return None
    entry: dict[str, Any] = {"text": text}
    if raw.get("chapter") is not None:
        try:
            entry["chapter"] = int(raw["chapter"])
        except (TypeError, ValueError):
            pass
    if raw.get("year"):
        entry["year"] = str(raw["year"]).strip()
    if raw.get("note"):
        entry["note"] = str(raw["note"]).strip()
    return entry


def _auto_timeline(project: Path) -> list[dict[str, Any]]:
    """`kb/outline/auto-timeline.md` 里是逐章抽取出的事件行，形如「- 第3章 …」。"""
    path = project / "kb" / "outline" / "auto-timeline.md"
    if not path.exists():
        return []
    _meta, body = parse_note(read_text(path))
    items: list[dict[str, Any]] = []
    for line in body.splitlines():
        text = line.strip().lstrip("-*").strip()
        if not text:
            continue
        chapter = _CHAPTER_RE.search(text)
        year = _YEAR_RE.search(text)
        # 行首的「第N章」由分组标题表达，正文里去掉，避免重复
        display = _CHAPTER_PREFIX_RE.sub("", text).strip() or text
        items.append(
            {
                "text": display,
                "chapter": int(chapter.group(1)) if chapter else None,
                "year": year.group(0) if year else "",
                "source_kind": "outline",
                "source_id": "auto-timeline",
                "source_name": "抽取事件",
            }
        )
    return items


def collect_timeline(project: Path, kinds: list[str] | None = None) -> dict[str, Any]:
    """汇总所有卡片 meta.timeline 与逐章抽取的事件，按章 / 按年代分两条轴。"""
    selected = [kind for kind in (kinds or KINDS) if kind in KINDS] or KINDS
    items: list[dict[str, Any]] = []
    order = 0

    for kind in selected:
        for entity in list_entities(project, kind):
            meta = entity.get("meta") or {}
            raw = meta.get("timeline")
            if not isinstance(raw, list):
                continue
            for entry_raw in raw:
                entry = _entry_of(entry_raw)
                if not entry:
                    continue
                order += 1
                chapter = entry.get("chapter")
                year = entry.get("year") or ""
                if chapter is not None:
                    axis, sort_no = "chapter", int(chapter)
                elif year:
                    match = _YEAR_RE.search(year)
                    axis, sort_no = "year", int(match.group(1)) if match else 0
                else:
                    axis, sort_no = "unknown", 0
                items.append(
                    {
                        **entry,
                        "axis": axis,
                        "order": sort_no,
                        "seq": order,
                        "source_kind": kind,
                        "source_id": str(entity["id"]),
                        "source_name": str(entity.get("title") or entity["id"]),
                    }
                )

    if "outline" in selected:
        for entry in _auto_timeline(project):
            order += 1
            chapter = entry.get("chapter")
            year = entry.get("year") or ""
            if chapter is not None:
                axis, sort_no = "chapter", int(chapter)
            elif year:
                axis, sort_no = "year", 0
            else:
                axis, sort_no = "unknown", 0
            items.append({**entry, "axis": axis, "order": sort_no, "seq": order})

    items.sort(key=lambda item: (item["axis"] != "chapter", item["order"], item["seq"]))
    axes = {
        axis: sum(1 for item in items if item["axis"] == axis)
        for axis in ("chapter", "year", "unknown")
    }
    return {"items": items, "total": len(items), "axes": axes}


# ---------------------------------------------------------------- 素材入库


def _normalize(text: str) -> str:
    """统一换行再比较：Windows 上写盘会把 \\n 变成 \\r\\n，直接比会判成不同内容。"""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def save_material(
    project: Path,
    text: str,
    *,
    title: str = "",
    source: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """把一段摘录收进 `kb/materials/`。

    同一段正文已收录过就直接返回旧条目；同名但内容不同则另存带序号的副本。
    """
    body = _normalize(text or "")
    if not body:
        raise MaterialError("素材内容为空")
    if len(body) > 20000:
        raise MaterialError(f"素材过长（{len(body)} 字），请分段收录")

    # 正文完全相同就当重复收录，不管这次填的标题是什么
    existing_items = list_entities(project, "materials")
    for entity in existing_items:
        if _normalize(str(entity.get("body") or "")) == body:
            return {**entity, "duplicate": True}

    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    name = (title or "").strip() or first_line[:16]
    entity_id = (safe_entity_id(name) or f"material-{int(time.time())}")[:48]
    meta: dict[str, Any] = {
        "name": name,
        "tags": [tag for tag in (tags or []) if tag],
        "source": source.strip(),
        "added_at": now_iso(),
    }
    if entity_file(project, "materials", entity_id).exists():
        # 同名不同内容：保留旧条目，另存一份带序号
        index = 2
        while entity_file(project, "materials", f"{entity_id}-{index}").exists():
            index += 1
        entity_id = f"{entity_id}-{index}"
        meta["name"] = f"{name}（{index}）"

    saved = save_entity(project, "materials", entity_id, meta, body)
    return {**saved, "duplicate": False}
