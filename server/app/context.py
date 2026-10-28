from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import memory
from .config import GLOBAL_SKILLS_DIR
from .domains import DomainPack, ToolContext, get_domain
from .kb.repository import dump_note, get_entity, parse_note
from .workspace import read_book_meta, safe_join

IDENTITY = """你是「墨」，一个本地桌面写作 Agent 的内核。
你能读写用户工作区的文件、检索书稿知识库、维护长期记忆，并在需要时调用工具真正落地修改。
回答用中文：先给结论，再展开依据；不确定就先问，不编造事实、设定或文件内容。"""

BUILDER_EXPERT = """你正在与用户一起创建一个写作专家。请通过提问确认：擅长领域、叙事风格、工作流程、禁忌事项。
信息足够后调用 expert_write 保存；expert_id 用简短英文或拼音，name 用中文，description 写清「什么时候该用这个专家」。
不要编造用户偏好，不确定就问。保存后告诉用户可在专家页选中并设为当前专家。"""

BUILDER_SKILL = """你正在创建一个技能。请确认：技能用途、触发场景、执行步骤、输出格式。
确认后调用 skill_write 保存；slug 用小写英文与连字符（中文名可留空自动生成），说明要具体可执行。"""

LIMITS = {
    "identity": 1200,
    "persona": 4200,
    "domain": 3500,
    "user": 1600,
    "long": 2600,
    "project": 3600,
    "references": 6000,
    "skills": 1600,
    "runtime": 1200,
}

LABELS = {
    "identity": "内核身份",
    "persona": "人格 / 专家",
    "domain": "域包规则",
    "user": "用户记忆",
    "long": "长期记忆",
    "project": "项目记忆",
    "references": "本轮引用",
    "skills": "技能索引",
    "runtime": "运行态",
}

_WS = re.compile(r"\s+")


@dataclass
class ContextItem:
    layer: str
    title: str
    source: str
    chars: int
    limit: int
    truncated: bool
    preview: str
    included: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContextBundle:
    system_prompt: str
    items: list[ContextItem] = field(default_factory=list)
    expert_id: str = ""
    domain_id: str = "book"
    fingerprint: str = ""
    total_chars: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_prompt": self.system_prompt,
            "items": [item.to_dict() for item in self.items],
            "expert_id": self.expert_id,
            "domain_id": self.domain_id,
            "fingerprint": self.fingerprint,
            "total_chars": self.total_chars,
        }


def assemble(
    project: Path,
    *,
    session: dict[str, Any] | None = None,
    expert: dict[str, Any] | None = None,
    domain: DomainPack | None = None,
    readonly: bool = False,
    builder: str = "",
    references: list[dict[str, Any]] | None = None,
) -> ContextBundle:
    """按层装配 system prompt，并产出可展示的注入清单。"""
    domain = domain or get_domain((session or {}).get("domain") or "book")
    memory.ensure_files(project)

    bundle = ContextBundle(system_prompt="", expert_id=(expert or {}).get("id", ""), domain_id=domain.id)
    blocks: list[str] = []

    def add(layer: str, title: str, source: str, text: str) -> None:
        text = (text or "").strip()
        limit = LIMITS[layer]
        included = bool(text)
        clipped = text[:limit].rstrip() if included else ""
        truncated = included and len(text) > limit
        if truncated:
            clipped += "\n…（已按层预算截断）"
        item = ContextItem(
            layer=layer,
            title=title or LABELS[layer],
            source=source,
            chars=len(text),
            limit=limit,
            truncated=truncated,
            preview=_preview(clipped),
            included=included,
        )
        bundle.items.append(item)
        if included:
            blocks.append(clipped)

    add("identity", LABELS["identity"], "kernel", IDENTITY)

    if expert:
        persona = _persona_block(expert)
        add("persona", f"专家 · {expert.get('name')}", expert.get("file", ""), persona)
    else:
        add("persona", "域默认人格", f"domain:{domain.id}", domain.persona)

    add("domain", f"域包 · {domain.name}", f"domain:{domain.id}", domain.rules)
    add("user", LABELS["user"], memory.memory_path("user").name, memory.read("user"))
    add("long", LABELS["long"], memory.memory_path("long").name, memory.read("long"))
    add(
        "project",
        LABELS["project"],
        "AGENTS.md",
        memory.read("project", project),
    )
    if references:
        add(
            "references",
            LABELS["references"],
            f"{len(references)} 项",
            _references_block(project, references),
        )
    add("skills", LABELS["skills"], str(Path(domain.skills_subdir) / "*" / "SKILL.md"), _skills_index(project, domain))

    runtime = _runtime_block(project, session, expert, readonly, builder)
    add("runtime", LABELS["runtime"], "runtime", runtime)

    bundle.system_prompt = "\n\n".join(blocks)
    bundle.total_chars = len(bundle.system_prompt)
    digest = hashlib.sha1(bundle.system_prompt.encode("utf-8")).hexdigest()[:12]
    bundle.fingerprint = f"{domain.id}:{bundle.expert_id or '-'}:{digest}"
    return bundle


def _persona_block(expert: dict[str, Any]) -> str:
    name = expert.get("name") or expert.get("id") or "专家"
    parts = [f'<persona name="{name}">']
    prompt = (expert.get("prompt") or "").strip()
    if prompt:
        parts.append(f"写作风格指令：{prompt}")
    body = (expert.get("body") or "").strip()
    if body:
        parts.append(body)
    skills = expert.get("skills") or []
    if skills:
        parts.append("启动时优先加载技能：" + "、".join(str(item) for item in skills))
    parts.append("</persona>")
    return "\n".join(parts)


def _skills_index(project: Path, domain: DomainPack) -> str:
    """列出项目与全局技能；全局目录通过 CompositeBackend 挂在 /global-skills。"""
    lines: list[str] = []
    roots = [(project / domain.skills_subdir, "项目"), (GLOBAL_SKILLS_DIR, "全局")]
    for root, scope in roots:
        if not root.exists():
            continue
        for file in sorted(root.glob("*/SKILL.md")):
            meta, body = parse_note(file.read_text(encoding="utf-8"))
            if meta.get("enabled") is False:
                continue
            name = meta.get("display_name") or meta.get("name") or file.parent.name
            description = meta.get("description") or _WS.sub(" ", body).strip()[:120]
            lines.append(f"- [{scope}] {name}（{file.parent.name}）：{description}")
    if not lines:
        return "（暂无技能。需要时可用 skill_write 创建。）"
    return "\n".join(lines)


def _references_block(project: Path, references: list[dict[str, Any]]) -> str:
    """把 @ 引用的实体/文件/章节/技能整块注入，带出处。"""
    blocks: list[str] = []
    for ref in references[:8]:
        kind = str(ref.get("type") or "")
        name = str(ref.get("name") or ref.get("id") or "")
        try:
            if kind == "entity":
                entity = get_entity(project, str(ref.get("kind") or ""), str(ref.get("id") or ""))
                if not entity:
                    blocks.append(f"<ref type=\"entity\" name=\"{name}\">未找到该条目</ref>")
                    continue
                blocks.append(
                    f'<ref type="entity" name="{entity["title"]}" '
                    f'source="{entity["file"]}">\n'
                    f"{dump_note(entity['meta'], entity['body'])}\n</ref>"
                )
            elif kind in {"file", "chapter", "skill"}:
                path = str(ref.get("path") or "")
                target = safe_join(project, path)
                if not target.exists():
                    blocks.append(f'<ref type="{kind}" source="{path}">文件不存在</ref>')
                    continue
                text = target.read_text(encoding="utf-8")
                blocks.append(
                    f'<ref type="{kind}" source="{path}">\n{_clip_ref(text)}\n</ref>'
                )
        except (ValueError, OSError) as exc:
            blocks.append(f'<ref type="{kind}" name="{name}">引用失败：{exc}</ref>')
    return "\n\n".join(blocks) or "（引用为空）"


def _clip_ref(text: str, limit: int = 4000) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n…（引用内容过长，已截断）"


def _runtime_block(
    project: Path,
    session: dict[str, Any] | None,
    expert: dict[str, Any] | None,
    readonly: bool,
    builder: str,
) -> str:
    meta = read_book_meta(project)
    progress = meta.get("progress") or {}
    lines = [
        f"当前日期：{datetime.now():%Y-%m-%d}",
        f"书稿：《{meta.get('title') or project.name}》，"
        f"进度：第{progress.get('volume', 1)}卷第{progress.get('chapter', 1)}章",
        f"项目目录：{project}",
    ]
    if session:
        lines.append(f"当前会话：{session.get('title') or '未命名'}（{session.get('kind') or 'main'}）")
    if expert:
        lines.append(f"当前专家：{expert.get('name')}（{expert.get('id')}）")
    if readonly:
        lines.append("这是一次侧问：只检索与回答，不要写入或修改任何文件，结论会展示在侧栏。")
    if builder == "expert":
        lines.append(BUILDER_EXPERT)
    elif builder == "skill":
        lines.append(BUILDER_SKILL)
    return "\n".join(lines)


def _preview(text: str) -> str:
    flat = _WS.sub(" ", text).strip()
    return flat[:180]


def tool_context(project: Path, *, project_id: str = "", session_id: str = "", readonly: bool = False) -> ToolContext:
    from .config import load_settings

    return ToolContext(
        project=project,
        embedding=load_settings().embedding,
        project_id=project_id,
        session_id=session_id,
        readonly=readonly,
    )
