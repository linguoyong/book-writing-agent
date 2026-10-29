from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from .repository import list_entities

# 「X 说 / X 道」这类对白引导词，用来抽取疑似人名
_SPEAK_RE = re.compile(r"([\u4e00-\u9fa5]{2,3})(?:说道|说|道|问道|喊道|笑道|低声道|沉声道|开口道)")
# 时间锚点：第 N 天/日/夜
_ANCHOR_RE = re.compile(r"第\s*([0-9零一二两三四五六七八九十百千]+)\s*(?:天|日|夜)")
# 不是人名的高频词（对白引导词前面的常见称谓/代词）
_COMMON_HEADS = {
    "他们", "她们", "它们", "自己", "众人", "大家", "两人", "三人", "几人",
    "老板", "老者", "少女", "少年", "男人", "女人", "孩子", "青年", "中年",
    "对方", "彼此", "声音", "心里", "身后", "这时", "有人", "谁", "师父",
    "陌生人", "一个", "两个", "几个", "那个", "这个",
    "徒弟", "师兄", "师姐", "师弟", "师妹", "父亲", "母亲", "爹", "娘",
}

FORESHADOW_OPEN = {"open", "planted", "未回收", "待回收"}


def _cn_to_int(text: str) -> int | None:
    text = text.strip()
    if text.isdigit():
        return int(text)
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000}
    section = 0
    number = 0
    for char in text:
        if char in digits:
            number = digits[char]
        elif char in units:
            section += (number or 1) * units[char]
            number = 0
        else:
            return None
    return section + number if section + number > 0 else None


def _load_chapters(project: Path) -> list[dict[str, Any]]:
    root = project / "manuscript"
    if not root.exists():
        return []
    chapters: list[dict[str, Any]] = []
    for file in sorted(root.rglob("*.md")):
        try:
            text = file.read_text(encoding="utf-8")
        except OSError:
            continue
        chapters.append(
            {
                "label": file.relative_to(project).as_posix()[:-3],
                "path": file,
                "text": text,
            }
        )
    return chapters


def _characters(project: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entity in list_entities(project, "characters"):
        meta = entity.get("meta") or {}
        raw_aliases = meta.get("aliases") or meta.get("alias") or ""
        if isinstance(raw_aliases, str):
            aliases = [item.strip() for item in re.split(r"[,，、;；/]", raw_aliases) if item.strip()]
        else:
            aliases = [str(item).strip() for item in raw_aliases if str(item).strip()]
        names = {str(entity.get("title") or entity["id"]).strip(), *aliases}
        result.append(
            {
                "id": entity["id"],
                "title": str(entity.get("title") or entity["id"]),
                "names": {name for name in names if name and len(name) >= 2},
                "meta": meta,
            }
        )
    return result


def lint_project(project: Path) -> dict[str, Any]:
    chapters = _load_chapters(project)
    characters = _characters(project)

    issues: list[dict[str, Any]] = []

    # 1. 角色别称混用：同一章里同一角色的多个称呼同时出现
    for character in characters:
        names = sorted(character["names"])
        if len(names) < 2:
            continue
        for chapter in chapters:
            present = [name for name in names if name in chapter["text"]]
            if len(present) >= 2:
                issues.append(
                    {
                        "rule": "alias_mix",
                        "severity": "warn",
                        "chapter": chapter["label"],
                        "message": f"「{character['title']}」在这一章混用了 {len(present)} 个称呼：{'、'.join(present)}",
                        "detail": "同一角色的多个称呼交错出现时，确认是否都是叙事视角需要的；不需要就统一。",
                    }
                )

    # 2. 未回收伏笔：meta.status 处于未回收状态
    foreshadows: list[dict[str, Any]] = []
    for kind in ("items", "world", "outline", "materials"):
        for entity in list_entities(project, kind):
            meta = entity.get("meta") or {}
            if str(meta.get("status") or "").strip().lower() in FORESHADOW_OPEN:
                foreshadows.append(
                    {
                        "id": entity["id"],
                        "title": entity.get("title") or entity["id"],
                        "kind": kind,
                        "planted_in": str(meta.get("planted_in") or meta.get("chapter") or ""),
                    }
                )
    if foreshadows:
        issues.append(
            {
                "rule": "foreshadow_open",
                "severity": "info",
                "chapter": "",
                "message": f"有 {len(foreshadows)} 条未回收的伏笔："
                + "；".join(
                    f"{item['title']}" + (f"（埋于 {item['planted_in']}）" if item["planted_in"] else "")
                    for item in foreshadows
                ),
                "detail": "给每条伏笔一个回收章节；写到大纲时标注「回收于」。",
            }
        )

    # 3. 时间线锚点倒退：按章节顺序比较「第 N 天」的最大值
    anchors: list[tuple[str, int | None, list[str]]] = []
    for chapter in chapters:
        found = _ANCHOR_RE.findall(chapter["text"])
        values = [value for value in (_cn_to_int(item[0]) for item in found) if value]
        anchors.append(
            (chapter["label"], max(values) if values else None, [f"第{v}天" for v in sorted(set(values))])
        )
    last_label = ""
    last_value = 0
    for label, value, shown in anchors:
        if value is None:
            continue
        if last_value and value < last_value:
            issues.append(
                {
                    "rule": "timeline_back",
                    "severity": "warn",
                    "chapter": label,
                    "message": f"时间线疑似倒退：{label} 出现 {'、'.join(shown)}，早于 {last_label} 的「第 {last_value} 天」",
                    "detail": "确认是插叙/闪回还是笔误；闪回建议在句首写明「三天前」这类相对表述。",
                }
            )
        else:
            last_label = label
            last_value = max(last_value, value)

    # 4. 疑似未登记角色：对白引导词前的名字不在角色库
    known = {name for character in characters for name in character["names"]}
    suspects: Counter[str] = Counter()
    suspect_chapters: dict[str, list[str]] = {}
    for chapter in chapters:
        for name in _SPEAK_RE.findall(chapter["text"]):
            if name in _COMMON_HEADS or name in known:
                continue
            if any(name in other for character in characters for other in character["names"]):
                continue
            suspects[name] += 1
            suspect_chapters.setdefault(name, []).append(chapter["label"])
    for name, _hint in suspects.most_common(12):
        # 出现次数按全文统计：对白引导只负责「发现」，正文重复出现才算可疑
        count = sum(chapter["text"].count(name) for chapter in chapters)
        if count >= 2:
            issues.append(
                {
                    "rule": "unknown_speaker",
                    "severity": "info",
                    "chapter": "、".join(suspect_chapters[name][:3]),
                    "message": f"疑似未登记的角色或称呼：「{name}」（全文出现 {count} 次）",
                    "detail": "如果这是正式角色，建议写入角色库并补充档案；如果只是临时称谓可忽略。",
                }
            )

    severity = Counter(issue["severity"] for issue in issues)
    return {
        "issues": issues,
        "stats": {
            "chapters": len(chapters),
            "characters": len(characters),
            "foreshadows": len(foreshadows),
            "warn": severity.get("warn", 0),
            "info": severity.get("info", 0),
        },
    }
