"""拆解：从一部成品小说里拆出「可复用的结构」和「可入库的设定」。

和 `extract.py` 的分工：

- `extract` 逐章抽事实，服务正在写的这本书（角色当前状态、事件线、伏笔）。
- `deconstruct` 拆别人写的书，服务开书前的对标与技法学习：结构骨架、爽点节奏、
  可迁移的写法，以及一批能直接进知识库的设定实体。

落地分三处：
1. 实体 → `extract.normalize()` + `apply_result()`，复用别名归并与待确认队列；
2. 技法 → `kb/materials` 卡片，按技法名去重；
3. 汇总 → 可选生成一个「拆解专家」+ 一个技能，走 `experts.save_expert` 与
   `skills/<slug>/SKILL.md`。

拆解默认按 3 章一组：整章整本地塞进上下文既超窗口，也会让模型只记得开头。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import usage
from .context import assemble_deconstruct
from .extract import ExtractStats, apply_result, build_entity_map, normalize
from .fileops import write_policy, write_project_text
from .import_book import chapter_number_from_title, parse_book
from .kb.repository import dump_note, list_entities, save_entity
from .llm import build_chat_model

GROUP_SIZE = 3
MAX_GROUPS = 200
MAX_GROUP_CHARS = 18_000
TECHNIQUE_DIR = "materials"

SCHEMA = """输出一个 JSON 对象，不要 markdown 代码块：

{
  "summary": "这组章节讲了什么，150 字以内",
  "structure": {
    "goal": "本组主要人物想达成什么",
    "conflict": "阻力是什么",
    "turn": "转折发生在哪里",
    "payoff": "给了读者什么兑现",
    "cliffhanger": "章末怎么留钩子"
  },
  "pacing": {"score": 1, "note": "节奏判断，30 字以内"},
  "techniques": [
    {"name": "技法名，不带专有名词", "how": "作者具体怎么做的", "when": "什么场景可复用"}
  ],
  "entities": {
    "characters": [{"name": "", "aliases": [], "role": "", "note": "", "confidence": 0.8}],
    "factions": [],
    "items": [],
    "locations": [],
    "events": [{"summary": "", "characters": [], "importance": "major"}],
    "foreshadowing": [{"text": ""}]
  }
}

约束：
- characters / factions / items / locations 的 name 必填，aliases 最多 4 个，
  role 不超过 30 字，note 不超过 60 字，confidence 取 0-1。
- events.summary 必填，characters 最多 4 个，importance 只能是 major 或 minor。
- foreshadowing.text 必填。
- techniques 最多 6 条；name 抹掉专有名词，how 说清「作者做了什么」，when 说清「什么场景能用」。
- 信息不足的字段留空数组，不要用常识补。"""


class DeconstructError(RuntimeError):
    """拆解失败，消息可直接展示给用户。"""


@dataclass
class DeconstructStats:
    groups: int = 0
    chapters: int = 0
    entities: int = 0
    techniques: int = 0
    failed: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)
    techniques_all: list[dict[str, str]] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)

    def as_dict(self, *, include_details: bool = True) -> dict[str, Any]:
        data = {
            "groups": self.groups,
            "chapters": self.chapters,
            "entities": self.entities,
            "techniques": self.techniques,
            "failed": self.failed,
        }
        if include_details:
            data["details"] = self.details[:50]
        return data


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeconstructError(f"拆解模型返回的不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise DeconstructError("拆解模型返回的结构不对，应为 JSON 对象")
    return data


def _slug(value: str) -> str:
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    if ascii_part:
        return ascii_part
    return "t-" + hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def _group_text(chapters: list[Any]) -> str:
    parts: list[str] = []
    total = 0
    for chapter in chapters:
        block = f"### {chapter.title}\n\n{chapter.body.strip()}"
        if total + len(block) > MAX_GROUP_CHARS:
            block = block[: max(0, MAX_GROUP_CHARS - total)]
        parts.append(block)
        total += len(block)
        if total >= MAX_GROUP_CHARS:
            break
    return "\n\n".join(parts)


def _chapter_no(chapter: Any, fallback: int) -> int:
    number = chapter_number_from_title(str(getattr(chapter, "title", "")))
    return number or fallback


def _save_techniques(project: Path, techniques: list[dict[str, str]], source: str) -> int:
    """技法写成 materials 卡，按名字去重：同一技法第二次出现只补出处。"""
    if not techniques:
        return 0
    existing = {
        str((item.get("meta") or {}).get("name") or item.get("title") or "")
        for item in list_entities(project, TECHNIQUE_DIR)
    }
    saved = 0
    for item in techniques[:12]:
        name = str(item.get("name") or "").strip()[:40]
        how = str(item.get("how") or "").strip()[:400]
        when = str(item.get("when") or "").strip()[:300]
        if not name or not how:
            continue
        if name in existing:
            continue
        entity_id = _slug(name)
        meta = {
            "id": entity_id,
            "name": name,
            "type": "technique",
            "tags": ["拆解", "技法"],
            "source": source,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        body = f"## 怎么做\n\n{how}\n\n## 什么时候用\n\n{when or '（模型未给出）'}\n"
        save_entity(project, TECHNIQUE_DIR, entity_id, meta, body)
        existing.add(name)
        saved += 1
    return saved


EXPERT_PROMPT = """下面是一本小说的拆解结果。请据此创建两个东西：

1. 一个「拆解专家」：人设是结构分析师，擅长把作品拆成可复用的骨架，
   不写正文、不模仿原文措辞。
2. 一个技能：把这本作品最突出的技法写成可执行流程（步骤 + 检查清单），
   不能出现原作的专有名词。

只输出 JSON：

{{
  "expert": {{
    "id": "英文短 id",
    "name": "专家名（中文，不超过 12 字）",
    "description": "一句话说明什么时候该用这个专家",
    "tags": ["2-3 个标签"],
    "prompt": "给写作 Agent 的一句话人设指令",
    "body": "Markdown 正文：拆解方法、关注维度、输出要求"
  }},
  "skill": {{
    "id": "英文短 id",
    "name": "技能名（中文）",
    "description": "一句话说明这个技能解决什么问题",
    "body": "Markdown 正文：可执行步骤 + 检查清单"
  }}
}}

结构摘要：
{summary}

高频技法：
{techniques}"""


def _create_expert(
    project: Path, stats: DeconstructStats, source_name: str
) -> dict[str, Any] | None:
    if not stats.summaries and not stats.techniques_all:
        return None
    from .experts import save_expert

    summary = "\n".join(f"- {item}" for item in stats.summaries[:20])
    techniques = "\n".join(
        f"- {item['name']}：{item['how']}" for item in stats.techniques_all[:20] if item.get("name")
    )
    model = build_chat_model("extractor")
    try:
        message = model.invoke(
            EXPERT_PROMPT.format(summary=summary or "（无）", techniques=techniques or "（无）")
        )
    except Exception as exc:  # noqa: BLE001 - 生成失败不影响拆解结果本身
        raise DeconstructError(f"专家生成失败：{type(exc).__name__}: {exc}") from exc
    content = getattr(message, "content", "")
    if isinstance(content, list):
        content = "".join(str(item) for item in content)
    data = _parse_json(str(content))

    expert = data.get("expert") or {}
    if not expert.get("name") or not expert.get("body"):
        return None
    expert_id = _slug(str(expert.get("id") or expert.get("name") or "deconstruct"))
    meta = {
        "name": str(expert.get("name"))[:40],
        "description": str(expert.get("description") or "")[:200],
        "tags": [str(item)[:16] for item in (expert.get("tags") or [])][:4],
        "prompt": str(expert.get("prompt") or "")[:400],
        "skills": [],
        "source": source_name,
    }
    save_expert(project, expert_id, meta, str(expert.get("body") or ""))

    skill = data.get("skill") or {}
    if skill.get("name") and skill.get("body"):
        skill_id = _slug(str(skill.get("id") or skill.get("name")))
        directory = project / "skills" / skill_id
        write_project_text(
            project,
            directory / "SKILL.md",
            dump_note(
                {
                    "name": skill_id,
                    "display_name": str(skill.get("name"))[:40],
                    "description": str(skill.get("description") or "")[:200],
                    "enabled": True,
                },
                str(skill.get("body") or ""),
            ),
        )
        save_expert(
            project,
            expert_id,
            {**meta, "skills": [skill_id]},
            str(expert.get("body") or ""),
        )

    return {"id": expert_id, "name": meta["name"]}


def run(
    project: Path,
    source: Path,
    *,
    group_size: int = GROUP_SIZE,
    max_groups: int = 0,
    create_expert: bool = False,
    project_id: str = "",
    progress: Callable[[dict[str, Any]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    sandbox: Any = None,
    allow_external: bool = False,
) -> dict[str, Any]:
    """拆一本书。返回统计与可选的专家信息。"""
    from .config import load_settings
    from .sandbox import check_path

    sandbox = sandbox if sandbox is not None else load_settings().sandbox
    source = source.expanduser().resolve()
    try:
        relative = source.relative_to(project.resolve()).as_posix()
        paths = [relative]
    except ValueError:
        if not allow_external:
            raise DeconstructError(
                "源文件超出项目目录，请先在拆解窗口选择外部文件，或将文件放入项目"
            ) from None
        # 外部文件由用户在界面明确选择，仍不能绕开 .env / secrets 等硬性拒绝规则。
        paths = [Path(*source.parts[index:]).as_posix() for index in range(1, len(source.parts))]
    if any(check_path(sandbox, path, "read") == "deny" for path in paths):
        raise DeconstructError("路径规则禁止读取该源文件")
    if source.suffix.lower() not in {".txt", ".md"}:
        raise DeconstructError("拆解源文件只支持 TXT 或 Markdown")
    with write_policy(sandbox):
        return _run(
            project,
            source,
            group_size=group_size,
            max_groups=max_groups,
            create_expert=create_expert,
            project_id=project_id,
            progress=progress,
            should_stop=should_stop,
        )


def _run(
    project: Path,
    source: Path,
    *,
    group_size: int,
    max_groups: int,
    create_expert: bool,
    project_id: str,
    progress: Callable[[dict[str, Any]], None] | None,
    should_stop: Callable[[], bool] | None,
) -> dict[str, Any]:
    if not source.exists() or not source.is_file():
        raise DeconstructError(f"源文件不存在：{source}")
    parsed = parse_book(source)
    chapters = [item for item in parsed.chapters if item.included]
    if not chapters:
        raise DeconstructError("没有识别到章节，请检查文件格式或章节规则")

    size = max(1, min(int(group_size or GROUP_SIZE), 10))
    groups = [chapters[index : index + size] for index in range(0, len(chapters), size)]
    if max_groups > 0:
        groups = groups[:max_groups]
    groups = groups[:MAX_GROUPS]

    model = build_chat_model("extractor")
    entities = build_entity_map(project)
    seen_events: set[str] = set()
    stats = DeconstructStats()
    source_name = source.name

    for index, group in enumerate(groups):
        if should_stop and should_stop():
            break
        text = _group_text(group)
        if not text.strip():
            continue
        try:
            context = assemble_deconstruct(
                project,
                source_text=text,
                schema=SCHEMA,
                note=f"这是第 {index + 1} 组，共 {len(groups)} 组；源文件：{source_name}",
            )
            message = model.invoke(
                context.system_prompt, config={"tags": ["book:internal", "book:metered"]}
            )
            if project_id:
                parsed_usage = usage.parse_message(message)
                usage.record(
                    project_id=project_id,
                    kind="deconstruct",
                    model=parsed_usage["model"],
                    input_tokens=parsed_usage["input"],
                    output_tokens=parsed_usage["output"],
                    cache_read=parsed_usage["cache_read"],
                    calls=1,
                )
            content = getattr(message, "content", "")
            if isinstance(content, list):
                content = "".join(str(item) for item in content)
            data = _parse_json(str(content))
        except Exception as exc:  # noqa: BLE001 - 单组失败不中断整本
            stats.failed += 1
            stats.details.append({"group": index + 1, "error": f"{type(exc).__name__}: {exc}"})
            if progress:
                progress(stats.as_dict(include_details=False))
            continue

        payload = data.get("entities") if isinstance(data.get("entities"), dict) else data
        normalized = normalize(payload)
        chapter_no = _chapter_no(group[0], index * size + 1)
        before = sum(
            len(normalized.get(key) or [])
            for key in ("characters", "factions", "items", "locations")
        )
        apply_result(
            project,
            chapter_no,
            normalized,
            ExtractStats(),
            entities=entities,
            seen_events=seen_events,
        )
        stats.entities += before

        structure = data.get("structure") if isinstance(data.get("structure"), dict) else {}
        summary = str(data.get("summary") or "").strip()
        if summary:
            stats.summaries.append(summary[:300])
        if structure:
            stats.summaries.append(
                "结构："
                + "；".join(f"{key}={str(value)[:40]}" for key, value in structure.items() if value)
            )
        techniques = data.get("techniques")
        if isinstance(techniques, list):
            clean = [
                {
                    "name": str(item.get("name") or "").strip()[:40],
                    "how": str(item.get("how") or "").strip()[:400],
                    "when": str(item.get("when") or "").strip()[:300],
                }
                for item in techniques
                if isinstance(item, dict) and item.get("name") and item.get("how")
            ]
            stats.techniques_all.extend(clean)
            stats.techniques += _save_techniques(project, clean, source_name)

        stats.groups += 1
        stats.chapters += len(group)
        if progress:
            progress(stats.as_dict(include_details=False))

    result = stats.as_dict()
    result["source"] = source_name
    if create_expert and not (should_stop and should_stop()):
        try:
            expert = _create_expert(project, stats, source_name)
        except DeconstructError as exc:
            result["expert_error"] = str(exc)
        else:
            if expert:
                result["expert"] = expert
    return result
