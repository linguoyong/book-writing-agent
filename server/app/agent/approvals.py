from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from ..kb.repository import dump_note, get_entity
from ..workspace import safe_join

MAX_DIFF_LINES = 160
ARGS_PREVIEW = 700

GATED_TOOLS = ("kb_write", "manuscript_write")


def build_requests(project: Path, value: dict[str, Any]) -> list[dict[str, Any]]:
    """把一次中断里的工具调用翻译成带 diff 的审批请求。"""
    requests: list[dict[str, Any]] = []
    for action in value.get("action_requests") or []:
        name = str(action.get("name") or "tool")
        args = action.get("args") or {}
        target, diff, note = describe(project, name, args)
        requests.append(
            {
                "name": name,
                "args": _preview_args(args),
                "description": action.get("description") or "",
                "target": target,
                "diff": diff,
                "note": note,
            }
        )
    return requests


def describe(project: Path, name: str, args: dict[str, Any]) -> tuple[str, str, str]:
    if name == "manuscript_write":
        return _manuscript_diff(project, args)
    if name == "kb_write":
        return _kb_diff(project, args)
    return "", "", ""


def _manuscript_diff(project: Path, args: dict[str, Any]) -> tuple[str, str, str]:
    relative = str(args.get("path") or "")
    content = str(args.get("content") or "")
    mode = str(args.get("mode") or "overwrite")
    try:
        target = safe_join(project / "manuscript", relative)
    except ValueError:
        return relative, "", "路径越界，无法预览"
    old = target.read_text(encoding="utf-8") if target.exists() else ""
    new = f"{old}\n\n{content}" if mode == "append" and old else content
    label = f"manuscript/{relative}"
    return label, _diff(old, new, label), "" if target.exists() else "新建文件"


def _kb_diff(project: Path, args: dict[str, Any]) -> tuple[str, str, str]:
    kind = str(args.get("kind") or "")
    entity_id = str(args.get("entity_id") or "")
    body = str(args.get("body") or "")
    try:
        meta = json.loads(args.get("meta_json") or "{}")
    except json.JSONDecodeError as exc:
        return f"kb/{kind}/{entity_id}", "", f"meta_json 不是合法 JSON：{exc}"
    existing = get_entity(project, kind, entity_id) if kind else None
    old = dump_note(existing["meta"], existing["body"]) if existing else ""
    merged = dict(meta or {})
    merged["id"] = entity_id
    new = dump_note(merged, body)
    label = f"kb/{kind}/{entity_id}.md"
    return label, _diff(old, new, label), "" if existing else "新建条目"


def _diff(old: str, new: str, label: str) -> str:
    if old == new:
        return "（内容无变化）"
    lines = list(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=f"a/{label}",
            tofile=f"b/{label}",
            lineterm="",
            n=3,
        )
    )
    if len(lines) > MAX_DIFF_LINES:
        lines = lines[:MAX_DIFF_LINES] + [f"…（diff 过长，仅显示前 {MAX_DIFF_LINES} 行）"]
    return "\n".join(lines)


def _preview_args(args: dict[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and len(value) > ARGS_PREVIEW:
            preview[key] = value[:ARGS_PREVIEW] + "…"
        else:
            preview[key] = value
    return preview
