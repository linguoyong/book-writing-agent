from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from ..kb.repository import dump_note, get_entity, parse_note
from ..text import read_text
from ..workspace import safe_join

MAX_DIFF_LINES = 160
ARGS_PREVIEW = 700

GATED_TOOLS = ("kb_write", "manuscript_write", "deconstruct_source")


def build_requests(project: Path, value: dict[str, Any]) -> list[dict[str, Any]]:
    """把一次中断里的工具调用翻译成带 diff 的审批请求。"""
    requests: list[dict[str, Any]] = []
    for action in value.get("action_requests") or []:
        name = str(action.get("name") or "tool")
        args = action.get("args") or {}
        target, diff, note = describe(project, name, args)
        # 记下审批那一刻目标文件的 mtime：用户点「通过」时工具会拿同一份 args
        # 对「当前」磁盘内容重放，期间若在编辑器里改过，diff 展示与实际落盘就不一致。
        mtime: int | None = None
        if target:
            try:
                file = safe_join(project, target)
                if file.exists():
                    mtime = int(file.stat().st_mtime * 1000)
            except (OSError, ValueError):
                mtime = None
        requests.append(
            {
                "name": name,
                "args": _preview_args(args),
                # 供「编辑后执行」使用：预览会截断长文本，编辑必须拿原文
                "raw_args": args,
                "description": action.get("description") or "",
                "target": target,
                "mtime": mtime,
                "diff": diff,
                "note": note,
            }
        )
    return requests


def describe(project: Path, name: str, args: dict[str, Any]) -> tuple[str, str, str]:
    if name == "deconstruct_source":
        return (
            "",
            "",
            (
                f"拆解 {args.get('path') or '源文件'}，最多 {args.get('groups', 3)} 组；"
                "将新增或合并知识库与素材卡"
                + ("，并生成专家与技能" if args.get("create_expert") else "")
            ),
        )
    if name == "manuscript_write":
        return _manuscript_diff(project, args)
    if name == "kb_write":
        return _kb_diff(project, args)
    if name == "write_file":
        return _fs_write_diff(project, args)
    if name == "edit_file":
        return _fs_edit_diff(project, args)
    if name == "delete":
        return _fs_delete_diff(project, args)
    return "", "", ""


def _manuscript_diff(project: Path, args: dict[str, Any]) -> tuple[str, str, str]:
    relative = str(args.get("path") or "")
    content = str(args.get("content") or "")
    mode = str(args.get("mode") or "overwrite")
    try:
        target = safe_join(project / "manuscript", relative)
    except ValueError:
        return relative, "", "路径越界，无法预览"
    old = read_text(target) if target.exists() else ""
    new = f"{old}\n\n{content}" if mode == "append" and old else content
    label = f"manuscript/{relative}"
    return label, _diff(old, new, label), _review_note(old, target.exists())


def _review_note(old: str, exists: bool) -> str:
    """审批卡上顺带说明这一章的审稿状态。

    不做硬拦截：本地写作工具，改个错别字也被拦会让人砸键盘。
    把状态摆在眼前，让人自己决定。
    """
    if not exists:
        return "新建文件"
    meta, _ = parse_note(old)
    review = meta.get("review") if isinstance(meta.get("review"), dict) else {}
    status = str(review.get("status") or "")
    if status == "fail":
        round_no = review.get("round") or 0
        return f"本章第 {round_no} 轮审稿未通过，建议先处理 P0 问题再覆盖"
    if status == "stale":
        return "本章正文改动后尚未重新审稿"
    if status == "pass":
        return f"本章已通过审稿（{review.get('score') or '-'} 分）；覆盖后需要重新审稿"
    return "本章尚未审稿"


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


def _fs_target(project: Path, args: dict[str, Any]) -> tuple[Path | None, str]:
    raw = str(args.get("file_path") or args.get("path") or "").strip()
    relative = raw.lstrip("/\\").replace("\\", "/")
    if not relative:
        return None, ""
    try:
        return safe_join(project, relative), relative
    except ValueError:
        return None, relative


def _fs_write_diff(project: Path, args: dict[str, Any]) -> tuple[str, str, str]:
    target, relative = _fs_target(project, args)
    if target is None:
        return relative, "", "路径越界，无法预览"
    old = read_text(target) if target.exists() else ""
    new = str(args.get("content") or "")
    return relative, _diff(old, new, relative), "" if target.exists() else "新建文件"


def _fs_edit_diff(project: Path, args: dict[str, Any]) -> tuple[str, str, str]:
    target, relative = _fs_target(project, args)
    if target is None:
        return relative, "", "路径越界，无法预览"
    if not target.exists():
        return relative, "", "文件不存在"
    old = read_text(target)
    needle = str(args.get("old_string") or "")
    replacement = str(args.get("new_string") or "")
    if not needle or needle not in old:
        return relative, "", "找不到待替换的文本，执行会失败"
    count = -1 if args.get("replace_all") else 1
    new = old.replace(needle, replacement, count)
    return relative, _diff(old, new, relative), ""


def _fs_delete_diff(project: Path, args: dict[str, Any]) -> tuple[str, str, str]:
    target, relative = _fs_target(project, args)
    if target is None:
        return relative, "", "路径越界，无法预览"
    old = read_text(target) if target.exists() else ""
    return relative, _diff(old, "", relative), "删除文件"


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
