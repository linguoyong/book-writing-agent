"""从已有作品导入：抽样 → 模型提炼 → 生成风格专家 + 写作技能。

约束（与用户确认过的方案一致）：
- 只做风格提炼，不提取角色名、地名等专有名词（举例一律抽象化）；
- 不保留原文，样本只在本次请求的内存里用完即弃；
- 专家管「像谁」（文风画像），技能管「怎么写」（可复用流程）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .kb.repository import dump_note, safe_entity_id
from .text import read_text, save_text

MAX_SOURCE_BYTES = 50 * 1024 * 1024
ALLOWED_SUFFIX = {".txt", ".md"}

# 片段配额：开头 / 中段 / 结尾 / 对话密集段
SAMPLE_HEAD = 5000
SAMPLE_MID = 4000
SAMPLE_TAIL = 3000
SAMPLE_DIALOGUE = 2500
DIALOGUE_MARKS = ("“", "”", "「", "『", '"')


class StyleImportError(Exception):
    """导入失败，消息可直接展示给用户。"""


def validate_source(path: Path) -> None:
    if not path.is_file():
        raise StyleImportError("文件不存在")
    if path.suffix.lower() not in ALLOWED_SUFFIX:
        raise StyleImportError("只支持 .txt 或 .md 文件")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise StyleImportError("文件超过 50MB，请先拆分后再导入")


def sample_text(text: str) -> str:
    """整本太长时抽样：开头 + 中段 + 结尾 + 对话最密集的一段，合计约 1.4 万字。"""
    text = text.strip()
    total = len(text)
    if total <= SAMPLE_HEAD + SAMPLE_MID + SAMPLE_TAIL + SAMPLE_DIALOGUE:
        return text

    head = text[:SAMPLE_HEAD]
    mid_start = (total - SAMPLE_MID) // 2
    middle = text[mid_start : mid_start + SAMPLE_MID]
    tail = text[total - SAMPLE_TAIL :]

    dialogue = _dialogue_dense(text, SAMPLE_DIALOGUE)
    parts = [head]
    for piece in (middle, dialogue, tail):
        if piece.strip():
            parts.append(piece)
    return "\n\n……\n\n".join(parts)


def _dialogue_dense(text: str, budget: int) -> str:
    """找对话符号密度最高的一块连续文本（按 2000 字窗口滑动）。"""
    if len(text) <= budget:
        return ""
    window = 2000
    best_start, best_score = 0, -1.0
    marks = sum(text.count(mark) for mark in DIALOGUE_MARKS)
    if marks == 0:
        return ""
    for start in range(0, len(text) - window, window // 2):
        chunk = text[start : start + window]
        score = sum(chunk.count(mark) for mark in DIALOGUE_MARKS) / window
        if score > best_score:
            best_start, best_score = start, score
    return text[best_start : best_start + budget]


PROMPT_TEMPLATE = """你是写作风格分析师。根据下面的小说片段，提炼这位作者的写作风格与可复用的写作技巧。

硬性要求：
1. 只做风格提炼：句长与节奏、人称与视角、对话风格、描写密度、意象与修辞偏好、章节结构习惯、情绪推进方式。
2. 严禁出现原文里的角色名、地名、门派、功法、物品等专有名词；需要举例时用「某角色」「某场景」这类抽象表述。
3. 不摘抄原文句子（单处引用不超过 10 字且仅限必要）。
4. 输出严格的 JSON 对象，除 JSON 外不要有任何其他文字：
{{
  "expert": {{
    "id": "英文短id（如 concise-grit）",
    "name": "风格专家名（如：冷峻简练·强节奏）",
    "description": "一句话说明这个专家适合什么场景",
    "tags": ["2-4 个风格标签"],
    "prompt": "给写作 Agent 的一句话人设指令",
    "body": "markdown 正文：风格画像，按维度分小节，最后给一份「写作约束清单」"
  }},
  "skill": {{
    "id": "英文短id（如 scene-rhythm）",
    "name": "技能名（如：场景节奏控制）",
    "description": "一句话说明这个技能解决什么问题",
    "body": "markdown 正文：可执行流程（步骤化 + 检查清单），不依赖任何原作专有名词"
  }}
}}

小说片段（可能因抽样而不连续）：
{sample}"""


def import_style(project: Path, source: Path) -> dict[str, Any]:
    validate_source(source)
    text = read_text(source)
    if len(text.strip()) < 800:
        raise StyleImportError("正文太短（少于 800 字），无法提炼风格")

    sample = sample_text(text)
    raw = _ask_model(PROMPT_TEMPLATE.replace("{sample}", _escape_braces(sample)))
    parsed = _parse_json(raw)

    expert = parsed.get("expert") or {}
    skill = parsed.get("skill") or {}
    if not expert.get("name") or not expert.get("body"):
        raise StyleImportError("模型没有返回有效的专家内容，请重试")

    expert_saved = _save_expert(project, expert)
    skill_saved = _save_skill(project, skill) if skill.get("body") else None
    if skill_saved:
        # 专家默认挂上同批生成的技能，启动时优先加载
        meta = {**expert_saved["meta"], "skills": [skill_saved["id"]]}
        _write_expert_file(project, expert_saved["id"], meta, expert_saved["body"])

    return {
        "expert": {"id": expert_saved["id"], "name": expert_saved["meta"]["name"]},
        "skill": {"id": skill_saved["id"], "name": skill_saved["name"]} if skill_saved else None,
    }


def _escape_braces(sample: str) -> str:
    return sample.replace("{", "{{").replace("}", "}}")


def _ask_model(prompt: str) -> str:
    from .llm import build_chat_model

    model = build_chat_model("extractor")
    result = model.invoke(prompt)
    content = result.content if isinstance(result.content, str) else str(result.content)
    if not content.strip():
        raise StyleImportError("模型返回为空，请重试")
    return content


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise StyleImportError("模型输出不是有效 JSON，请重试")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise StyleImportError(f"模型输出解析失败：{error}") from error
    if not isinstance(parsed, dict):
        raise StyleImportError("模型输出结构不符合预期，请重试")
    return parsed


def _unique_id(project: Path, base: str, directory: Path) -> str:
    base_id = safe_entity_id(base)
    candidate, counter = base_id, 2
    while (directory / f"{candidate}.md").exists() or (directory / candidate).exists():
        candidate = f"{base_id}-{counter}"
        counter += 1
    return candidate


def _save_expert(project: Path, expert: dict[str, Any]) -> dict[str, Any]:
    from .experts import save_expert

    expert_id = _unique_id(project, str(expert.get("id") or "style"), project / "experts")
    saved = save_expert(
        project,
        expert_id,
        {
            "name": str(expert["name"])[:40],
            "description": str(expert.get("description") or "")[:200],
            "tags": [str(tag)[:20] for tag in (expert.get("tags") or [])][:4],
            "prompt": str(expert.get("prompt") or "")[:400],
        },
        str(expert["body"]),
    )
    return {"id": expert_id, "meta": {"name": saved["name"]}, "body": str(expert["body"])}


def _write_expert_file(
    project: Path, expert_id: str, meta: dict[str, Any], body: str
) -> None:
    from .experts import expert_dir

    file = expert_dir(project) / f"{safe_entity_id(expert_id)}.md"
    save_text(file, dump_note(meta, body))


def _save_skill(project: Path, skill: dict[str, Any]) -> dict[str, Any] | None:
    skills_dir = project / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    skill_id = _unique_id(project, str(skill.get("id") or "style-flow"), skills_dir)
    directory = skills_dir / skill_id
    directory.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": str(skill.get("name") or skill_id)[:40],
        "description": str(skill.get("description") or "")[:200],
    }
    save_text(directory / "SKILL.md", dump_note(meta, str(skill["body"])))
    return {"id": skill_id, "name": meta["name"]}
