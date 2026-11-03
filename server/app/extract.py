from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import usage
from .kb.repository import dump_note, list_entities, parse_note, safe_entity_id, save_entity
from .kb.search import invalidate_entities
from .llm import build_chat_model
from .text import read_text, save_text
from .workspace import read_book_meta

KINDS_FOR_EXTRACT = ("characters", "locations", "factions", "items")
KIND_LABELS = {
    "characters": "角色",
    "locations": "地点",
    "factions": "势力",
    "items": "物品",
}
MAX_CHAPTER_CHARS = 6000
EXTRACT_WORKERS = 6
STATE_FILE = "extract.json"
CANDIDATE_THRESHOLD = 0.55

PROMPT = """你在为一部小说建立设定库。下面是第 {chapter} 章的正文，只抽取**本章明确出现**的信息。

只输出一个 JSON 对象，不要 markdown 代码块，不要解释：
{{
  "characters": [{{"name": "", "aliases": [], "role": "", "note": "", "confidence": 0.0}}],
  "locations": [{{"name": "", "note": "", "confidence": 0.0}}],
  "factions": [{{"name": "", "note": "", "confidence": 0.0}}],
  "items": [{{"name": "", "note": "", "confidence": 0.0}}],
  "events": [{{"summary": "", "characters": [], "importance": "major"}}],
  "foreshadowing": [{{"text": ""}}]
}}

规则：
- name 用正文里的正式称呼；aliases 只收本章出现过的别称，没有就空数组。
- role 一句话（≤20 字）；note 一句话（≤40 字）；不确定就留空字符串。
- events 最多 3 条，只记推动剧情的；foreshadowing 最多 2 条；没有就空数组。
- confidence 0–1，表示你对「这是一条值得入库的设定」的把握。
- 本章没有任何可抽取内容时，所有数组留空。

正文：
{text}"""

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)
_LIMITS = {
    "characters": 8,
    "locations": 5,
    "factions": 4,
    "items": 5,
    "events": 3,
    "foreshadowing": 2,
}


class ExtractError(RuntimeError):
    """抽取失败，消息可直接展示给用户。"""


@dataclass
class ExtractStats:
    chapters: int = 0
    characters: int = 0
    locations: int = 0
    factions: int = 0
    items: int = 0
    aliases: int = 0
    events: int = 0
    foreshadowing: int = 0
    failed: int = 0
    candidates: int = 0
    queued: int = 0
    notes: int = 0
    duplicates: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)

    def add(self, other: "ExtractStats") -> None:
        for key in (
            "chapters", "characters", "locations", "factions", "items",
            "aliases", "events", "foreshadowing", "failed", "candidates",
            "queued", "notes", "duplicates",
        ):
            setattr(self, key, getattr(self, key) + getattr(other, key))
        self.details.extend(other.details)
        for sample in other.samples:
            if sample not in self.samples and len(self.samples) < 20:
                self.samples.append(sample)

    def as_dict(self) -> dict[str, Any]:
        return {
            "chapters": self.chapters,
            "characters": self.characters,
            "locations": self.locations,
            "factions": self.factions,
            "items": self.items,
            "aliases": self.aliases,
            "events": self.events,
            "foreshadowing": self.foreshadowing,
            "failed": self.failed,
            "candidates": self.candidates,
            "queued": self.queued,
            "notes": self.notes,
            "duplicates": self.duplicates,
            "details": self.details[:50],
            "samples": self.samples[:20],
        }


def chapter_files(project: Path) -> list[Path]:
    directory = project / "chapters"
    if not directory.exists():
        return []
    return sorted(directory.glob("*.md"))


def _chapter_meta(path: Path) -> tuple[int, str, str]:
    meta, body = parse_note(read_text(path))
    number = int(meta.get("chapter") or 0) or _number_from_name(path.stem)
    title = str(meta.get("title") or path.stem)
    return number, title, body


def _number_from_name(stem: str) -> int:
    match = re.match(r"(\d+)", stem)
    return int(match.group(1)) if match else 0


def state_path(project: Path) -> Path:
    return project / ".index" / STATE_FILE


def load_state(project: Path) -> dict[str, Any]:
    path = state_path(project)
    if not path.exists():
        return {"done": {}, "stats": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"done": {}, "stats": {}}


def save_state(project: Path, state: dict[str, Any]) -> None:
    path = state_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_text(path, json.dumps(state, ensure_ascii=False, indent=2))


def _clean(value: Any, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _as_list(value: Any, limit: int) -> list[Any]:
    if not isinstance(value, list):
        return []
    return value[:limit]


def normalize(data: Any) -> dict[str, list[dict[str, Any]]]:
    """把模型输出收拾成固定结构：长度、类型、空值都兜住。"""
    if not isinstance(data, dict):
        return {key: [] for key in _LIMITS}

    result: dict[str, list[dict[str, Any]]] = {}
    for kind in ("characters", "locations", "factions", "items"):
        items = []
        for raw in _as_list(data.get(kind), _LIMITS[kind]):
            if not isinstance(raw, dict):
                continue
            name = _clean(raw.get("name"), 30)
            if not name:
                continue
            aliases = [
                _clean(item, 20)
                for item in _as_list(raw.get("aliases"), 4)
                if _clean(item, 20) and _clean(item, 20) != name
            ]
            items.append(
                {
                    "name": name,
                    "aliases": aliases,
                    "role": _clean(raw.get("role"), 30),
                    "note": _clean(raw.get("note"), 60),
                    "confidence": _confidence(raw.get("confidence")),
                }
            )
        result[kind] = items

    events = []
    for raw in _as_list(data.get("events"), _LIMITS["events"]):
        if not isinstance(raw, dict):
            continue
        summary = _clean(raw.get("summary"), 80)
        if not summary:
            continue
        events.append(
            {
                "summary": summary,
                "characters": [_clean(item, 20) for item in _as_list(raw.get("characters"), 4)],
                "importance": "major" if raw.get("importance") == "major" else "minor",
            }
        )
    result["events"] = events

    foreshadowing = []
    for raw in _as_list(data.get("foreshadowing"), _LIMITS["foreshadowing"]):
        if isinstance(raw, dict):
            text = _clean(raw.get("text"), 80)
        else:
            text = _clean(raw, 80)
        if text:
            foreshadowing.append({"text": text})
    result["foreshadowing"] = foreshadowing
    return result


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.6


def parse_response(text: str) -> dict[str, list[dict[str, Any]]]:
    match = _JSON_BLOCK.search(text or "")
    if not match:
        raise ExtractError("模型没有返回 JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ExtractError(f"JSON 解析失败：{exc}") from exc
    return normalize(data)


def extract_chapter(
    chapter_no: int,
    body: str,
    model: Any,
    on_usage: Callable[[Any], None] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    text = body.strip()[:MAX_CHAPTER_CHARS]
    if not text:
        return {key: [] for key in _LIMITS}
    prompt = PROMPT.format(chapter=chapter_no, text=text)
    try:
        message = model.invoke(prompt)
    except Exception as exc:  # noqa: BLE001 - 模型侧异常统一转成可读错误
        raise ExtractError(f"{type(exc).__name__}: {exc}") from exc
    if on_usage:
        on_usage(message)
    content = getattr(message, "content", "")
    if isinstance(content, list):
        content = "".join(str(item) for item in content)
    return parse_response(str(content))


# ---------------------------------------------------------------- 落库（实体归并）


def build_entity_map(project: Path) -> dict[str, dict[str, Any]]:
    """名字/别名 → 实体快照，整个抽取任务里复用一个。

    每章都重新扫一遍 kb 目录的话，几千章就是几十万次文件读取。
    新建的实体在落库时就地写回这张表，后面的章节能立刻按别名命中。
    """
    index: dict[str, dict[str, Any]] = {}
    for kind in KINDS_FOR_EXTRACT:
        for entity in list_entities(project, kind):
            entity_id = str(entity.get("id") or "")
            if not entity_id:
                continue
            meta = dict(entity.get("meta") or {})
            snapshot = {
                "kind": kind,
                "id": entity_id,
                "meta": meta,
                "body": str(entity.get("body") or ""),
            }
            names = [str(meta.get("name") or entity.get("title") or entity_id)]
            aliases = meta.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [
                    item.strip()
                    for item in re.split(r"[,，、;；/|]", aliases)
                    if item.strip()
                ]
            names.extend(str(item) for item in aliases if item)
            for name in names:
                index.setdefault(name.strip(), snapshot)
    return index


def _append_line(project: Path, line: str) -> None:
    """时间线与伏笔都往同一个自动文件里追加，不回头重写整本。"""
    path = project / "kb" / "outline" / "auto-timeline.md"
    if not path.exists():
        meta = {
            "id": "auto-timeline",
            "name": "自动抽取时间线",
            "type": "outline",
            "tags": ["自动", "事件"],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        save_text(path, dump_note(meta, "\n"))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line.rstrip() + "\n")


def _merge_aliases(project: Path, snapshot: dict[str, Any], aliases: list[str]) -> int:
    """把新别名并进已有实体卡，返回新增数量。"""
    meta = dict(snapshot.get("meta") or {})
    current = list(meta.get("aliases") or [])
    new_aliases = [alias for alias in aliases if alias and alias not in current]
    if not new_aliases:
        return 0
    meta["aliases"] = list(dict.fromkeys([*current, *new_aliases]))
    save_entity(project, snapshot["kind"], snapshot["id"], meta, str(snapshot.get("body") or ""))
    snapshot["meta"] = meta
    return len(new_aliases)


AUTO_SECTION = "## 自动摘要"
CANDIDATES_FILE = "extract-candidates.json"
MAX_NOTES = 20


def candidates_path(project: Path) -> Path:
    return project / ".index" / CANDIDATES_FILE


def load_candidates(project: Path) -> list[dict[str, Any]]:
    path = candidates_path(project)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def save_candidates(project: Path, items: list[dict[str, Any]]) -> None:
    path = candidates_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_text(path, json.dumps(items, ensure_ascii=False, indent=2))


def queue_candidate(
    project: Path,
    *,
    chapter_no: int,
    kind: str,
    item: dict[str, Any],
    reason: str,
) -> bool:
    """低置信或冲突的条目先搁在待确认队列里，不直接写库。"""
    items = load_candidates(project)
    candidate_id = f"{kind}:{safe_entity_id(item['name'])}"
    if any(entry.get("id") == candidate_id for entry in items):
        return False
    items.append(
        {
            "id": candidate_id,
            "kind": kind,
            "name": item["name"],
            "aliases": item["aliases"],
            "role": item.get("role", ""),
            "note": item.get("note", ""),
            "confidence": item.get("confidence", 0.0),
            "chapter": chapter_no,
            "reason": reason,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    save_candidates(project, items)
    return True


def _create_stub(
    project: Path, kind: str, item: dict[str, Any], chapter_no: int
) -> dict[str, Any]:
    entity_id = safe_entity_id(item["name"])
    meta = {
        "id": entity_id,
        "name": item["name"],
        "type": "character" if kind == "characters" else kind[:-1],
        "status": "自动",
        "source": "auto",
        "first_chapter": chapter_no,
        "aliases": item["aliases"],
    }
    lines = ["## 自动抽取", f"- 首次出现：第{chapter_no}章"]
    if item.get("role"):
        lines.append(f"- 定位：{item['role']}")
    if item.get("note"):
        lines.append(f"- 描述：{item['note']}")
    body = "\n".join(lines)
    save_entity(project, kind, entity_id, meta, body)
    return {"kind": kind, "id": entity_id, "meta": meta, "body": body}


def _merge_note(project: Path, snapshot: dict[str, Any], chapter_no: int, note: str) -> bool:
    """把这一章的一句话描述追加到卡片的「自动摘要」小节。

    只动自动管理的小节，人工写的正文一个字都不碰；同一章只留一条，
    最多保留最近 20 条，避免长书把卡片撑爆。
    """
    note = (note or "").strip()
    if not note:
        return False
    body = str(snapshot.get("body") or "")
    marker = f"- 第{chapter_no}章："
    head = body
    bullets: list[str] = []
    index = body.find(AUTO_SECTION)
    if index >= 0:
        head = body[:index].rstrip()
        for line in body[index + len(AUTO_SECTION):].splitlines():
            if line.strip().startswith("- 第"):
                bullets.append(line.strip())
    if any(line.startswith(marker) for line in bullets):
        return False

    bullets.append(f"{marker}{note}")

    def number(line: str) -> int:
        match = re.match(r"- 第(\d+)章", line)
        return int(match.group(1)) if match else 0

    bullets.sort(key=number)
    bullets = bullets[-MAX_NOTES:]
    new_body = f"{head}\n\n{AUTO_SECTION}\n" + "\n".join(bullets) + "\n"
    meta = dict(snapshot.get("meta") or {})
    save_entity(project, snapshot["kind"], snapshot["id"], meta, new_body)
    snapshot["body"] = new_body
    return True


def _event_key(summary: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]", "", summary)[:24]


def accept_candidate(project: Path, candidate_id: str) -> dict[str, Any] | None:
    items = load_candidates(project)
    target = next((entry for entry in items if entry.get("id") == candidate_id), None)
    if target is None:
        return None
    _create_stub(
        project,
        target["kind"],
        {
            "name": target["name"],
            "aliases": list(target.get("aliases") or []),
            "role": target.get("role", ""),
            "note": target.get("note", ""),
        },
        int(target.get("chapter") or 0),
    )
    save_candidates(project, [entry for entry in items if entry.get("id") != candidate_id])
    invalidate_entities(project)
    return target


def reject_candidate(project: Path, candidate_id: str) -> bool:
    items = load_candidates(project)
    remaining = [entry for entry in items if entry.get("id") != candidate_id]
    if len(remaining) == len(items):
        return False
    save_candidates(project, remaining)
    return True


def apply_result(
    project: Path,
    chapter_no: int,
    data: dict[str, list[dict[str, Any]]],
    stats: ExtractStats,
    *,
    dry_run: bool = False,
    entities: dict[str, dict[str, Any]] | None = None,
    seen_events: set[str] | None = None,
) -> ExtractStats:
    """把一章的抽取结果并入知识库；dry_run 只统计不落盘。"""
    index = entities if entities is not None else build_entity_map(project)
    seen = seen_events if seen_events is not None else set()

    for kind in ("characters", "locations", "factions", "items"):
        for item in data.get(kind, []):
            name = item["name"]
            snapshot = index.get(name)
            if snapshot is None:
                for alias in item["aliases"]:
                    snapshot = index.get(alias)
                    if snapshot:
                        break

            if snapshot is not None:
                # 别名已经属于别的实体：多半是重名，别硬并
                conflict = next(
                    (
                        alias
                        for alias in item["aliases"]
                        if index.get(alias) is not None
                        and index[alias]["id"] != snapshot["id"]
                    ),
                    None,
                )
                if conflict:
                    if not dry_run:
                        queue_candidate(
                            project,
                            chapter_no=chapter_no,
                            kind=kind,
                            item=item,
                            reason=f"别名「{conflict}」已属于「{index[conflict]['meta'].get('name')}」",
                        )
                    stats.queued += 1
                    continue

                if dry_run:
                    meta = snapshot.get("meta") or {}
                    stats.aliases += len(
                        [a for a in item["aliases"] if a not in (meta.get("aliases") or [])]
                    )
                    continue

                added = _merge_aliases(project, snapshot, item["aliases"])
                stats.aliases += added
                for alias in item["aliases"]:
                    index.setdefault(alias, snapshot)
                if _merge_note(project, snapshot, chapter_no, item.get("note", "")):
                    stats.notes += 1
                continue

            # 新实体：置信度太低先放队列，够可信才直接建卡
            if item.get("confidence", 1.0) < CANDIDATE_THRESHOLD:
                if not dry_run:
                    queue_candidate(
                        project,
                        chapter_no=chapter_no,
                        kind=kind,
                        item=item,
                        reason=f"置信度 {item.get('confidence', 0):.2f} 偏低",
                    )
                stats.queued += 1
                continue

            stats.candidates += 1
            setattr(stats, kind, getattr(stats, kind) + 1)
            label = KIND_LABELS.get(kind, kind)
            sample = f"{label}：{name}"
            if sample not in stats.samples and len(stats.samples) < 20:
                stats.samples.append(sample)
            snapshot = {
                "kind": kind,
                "id": safe_entity_id(name),
                "meta": {"name": name, "aliases": item["aliases"]},
                "body": "",
            }
            index[name] = snapshot
            for alias in item["aliases"]:
                index.setdefault(alias, snapshot)
            if dry_run:
                continue
            snapshot.update(_create_stub(project, kind, item, chapter_no))

    for event in data.get("events", []):
        key = _event_key(event["summary"])
        if key and key in seen:
            stats.duplicates += 1
            continue
        if key:
            seen.add(key)
        stats.events += 1
        if dry_run:
            continue
        who = "、".join(event["characters"][:3])
        suffix = f"（{who}）" if who else ""
        _append_line(project, f"- [事件][第{chapter_no}章] {event['summary']}{suffix}")

    for item in data.get("foreshadowing", []):
        stats.foreshadowing += 1
        if dry_run:
            continue
        _append_line(project, f"- [伏笔][第{chapter_no}章] {item['text']}")

    if not dry_run:
        invalidate_entities(project)
    return stats


def sort_timeline(project: Path) -> None:
    """并发落库会让时间线按完成顺序排列，收尾时按章号重排一次。"""
    path = project / "kb" / "outline" / "auto-timeline.md"
    if not path.exists():
        return
    meta, body = parse_note(read_text(path))
    lines = [line for line in body.splitlines() if line.strip()]

    def chapter_key(line: str) -> int:
        match = re.search(r"第(\d+)章", line)
        return int(match.group(1)) if match else 0

    if lines != sorted(lines, key=chapter_key):
        save_text(path, dump_note(meta, "\n".join(sorted(lines, key=chapter_key))))


def remaining_chapters(project: Path) -> list[tuple[int, str, Path]]:
    state = load_state(project)
    done = state.get("done") or {}
    result = []
    for file in chapter_files(project):
        number, title, _ = _chapter_meta(file)
        if str(number) in done or not number:
            continue
        result.append((number, title, file))
    return result


def run(
    project: Path,
    *,
    limit: int = 0,
    dry_run: bool = False,
    progress: Callable[[dict[str, Any]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    project_id: str = "",
) -> dict[str, Any]:
    """逐章抽取。limit=0 表示全部；失败不中断，记在 failed 里。

    LLM 调用占绝大部分时间，所以并发跑几个章节；**落库仍然串行**，
    避免同一张卡被两个线程同时改写。
    """
    targets = remaining_chapters(project)
    if limit > 0:
        targets = targets[:limit]
    total = len(targets)
    if not total:
        return ExtractStats().as_dict()

    model = build_chat_model("extractor")
    state = load_state(project)
    done = state.setdefault("done", {})
    entities = build_entity_map(project)
    # 事件去重跨章节生效：同一件事在多章被抽出来只留第一条
    seen_events: set[str] = set(state.get("event_keys") or [])
    stats = ExtractStats()
    finished = 0

    def count_usage(message: Any) -> None:
        # 抽取每章一次调用，逐次记账；没有 project_id（单测）时跳过
        if not project_id:
            return
        parsed = usage.parse_message(message)
        usage.record(
            project_id=project_id,
            kind="extract",
            model=parsed["model"],
            input_tokens=parsed["input"],
            output_tokens=parsed["output"],
            cache_read=parsed["cache_read"],
            calls=1,
        )

    def work(item: tuple[int, str, Path]) -> tuple[tuple[int, str, Path], Any, str]:
        number, title, file = item
        try:
            _, _, body = _chapter_meta(file)
            return (
                item,
                extract_chapter(number, body, model, on_usage=count_usage),
                "",
            )
        except (ExtractError, OSError) as exc:
            return item, None, str(exc)

    with ThreadPoolExecutor(max_workers=EXTRACT_WORKERS) as pool:
        futures = [pool.submit(work, item) for item in targets]
        try:
            for future in as_completed(futures):
                item, data, error = future.result()
                number, title, _ = item
                finished += 1
                if error or data is None:
                    stats.failed += 1
                    stats.details.append({"chapter": number, "title": title, "error": error})
                else:
                    chapter_stats = apply_result(
                        project, number, data, ExtractStats(),
                        dry_run=dry_run, entities=entities, seen_events=seen_events,
                    )
                    stats.add(chapter_stats)
                    stats.chapters += 1
                    if not dry_run:
                        done[str(number)] = {
                            "title": title,
                            "characters": len(data.get("characters", [])),
                            "events": len(data.get("events", [])),
                        }
                if progress:
                    progress(
                        {
                            "done": finished,
                            "total": total,
                            "chapter": number,
                            "title": title,
                            "stats": stats.as_dict(),
                        }
                    )
                if not dry_run and finished % 5 == 0:
                    state["stats"] = stats.as_dict()
                    save_state(project, state)
                if should_stop and should_stop():
                    break
        finally:
            for future in futures:
                future.cancel()

    if not dry_run:
        if stats.chapters:
            sort_timeline(project)
        state["event_keys"] = sorted(seen_events)
        state["stats"] = stats.as_dict()
        state["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_state(project, state)
    return stats.as_dict()


class ExtractJob:
    """后台抽取任务的进度与中止开关（进程内，够用且不引额外依赖）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._stop: dict[str, bool] = {}

    def start(self, project_id: str) -> bool:
        with self._lock:
            if self._jobs.get(project_id, {}).get("running"):
                return False
            self._jobs[project_id] = {
                "running": True,
                "done": 0,
                "total": 0,
                "chapter": 0,
                "title": "",
                "error": None,
                "stats": {},
            }
            self._stop[project_id] = False
            return True

    def update(self, project_id: str, **fields: Any) -> None:
        with self._lock:
            current = dict(self._jobs.get(project_id) or {})
            current.update(fields)
            self._jobs[project_id] = current

    def finish(self, project_id: str, **fields: Any) -> None:
        with self._lock:
            current = dict(self._jobs.get(project_id) or {})
            current.update(fields)
            current["running"] = False
            self._jobs[project_id] = current

    def stop(self, project_id: str) -> bool:
        with self._lock:
            if not self._jobs.get(project_id, {}).get("running"):
                return False
            self._stop[project_id] = True
            return True

    def stopped(self, project_id: str) -> bool:
        return bool(self._stop.get(project_id))

    def status(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(
                self._jobs.get(project_id)
                or {"running": False, "done": 0, "total": 0, "error": None, "stats": {}}
            )


jobs = ExtractJob()


def progress_summary(project: Path) -> dict[str, Any]:
    state = load_state(project)
    done = len(state.get("done") or {})
    total = len(chapter_files(project))
    return {
        "done": done,
        "total": total,
        "stats": state.get("stats") or {},
        "updated_at": state.get("updated_at") or "",
        "book": read_book_meta(project).get("title", ""),
    }
