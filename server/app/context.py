from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import memory, prompts
from .config import GLOBAL_SKILLS_DIR, load_settings
from .domains import DomainPack, ToolContext, get_domain
from .kb.repository import KINDS, dump_note, get_entity, list_entities, parse_note, trim_meta
from .sandbox import check_path
from .stats import compute as compute_stats
from .text import read_text
from .workspace import read_book_meta, safe_join

IDENTITY = """你是「文」，一个本地桌面写作 Agent 的内核。
你能读写用户工作区的文件、检索书稿知识库、维护长期记忆，并在需要时调用工具真正落地修改。
回答用中文：先给结论，再展开依据；不确定就先问，不编造事实、设定或文件内容。"""

BUILDER_EXPERT = """你正在与用户一起创建一个写作专家。请通过提问确认：擅长领域、叙事风格、工作流程、禁忌事项。
信息足够后调用 expert_write 保存；expert_id 用简短英文或拼音，name 用中文，description 写清「什么时候该用这个专家」。
不要编造用户偏好，不确定就问。保存后告诉用户可在专家页选中并设为当前专家。"""

BUILDER_SKILL = """你正在创建一个技能。请确认：技能用途、触发场景、执行步骤、输出格式。
确认后调用 skill_write 保存；slug 用小写英文与连字符（中文名可留空自动生成），说明要具体可执行。"""

REVIEWER = """你是「审稿人」，一个只做评判、不改稿的资深小说编辑。
你的职责是判断这一章能不能作为「完成稿」交付，而不是替作者重写。

三条铁律：
1. 每条问题必须引用本章原文（逐字片段）。找不到原文依据的判断，不要写。
2. 只评判，不代笔。可以指出「这里该收紧」，但不要输出改写后的完整段落。
3. 分数要能对应到问题：没有 P0 问题不该给低分，有 P0 问题不该给高分。

你看不到作者的写作意图，也不该去猜。你只看已经落在纸面上的文字。"""

RUBRIC = """评分维度（每项 1-5 分，5 最好）：

1. 设定一致性：人名、称谓、能力边界、时间线、地点是否与设定摘要或前文冲突。
2. 结构完整性：本章是否有明确的场景目标、阻力、转折、结果；有没有半截场景。
3. 节奏：信息密度是否均匀，有无连续多段没有推进的说明或对话。
4. 人物声音：对话是否符合该角色的身份、教育程度、当前情绪；有无「所有角色一个腔调」。
5. 钩子与爽点：章末是否留下继续读的理由；本章的期待 / 兑现 / 加压是否成立。
6. 文字冗余：重复表述、形容词堆叠、无信息量的过场。

问题分级：
- P0 必须改：设定冲突、逻辑断裂、关键场景缺失、人物行为没有动机。
- P1 应该改：节奏拖沓、对话失真、钩子偏弱、信息给得太直。
- P2 可以改：措辞、重复、标点、可有可无的描写。

判定标准：P0 为零，且六项平均分 >= 3.5，才算 pass。"""

KIND_LABELS = {
    "characters": "角色",
    "factions": "势力",
    "items": "物品",
    "locations": "地点",
    "world": "世界观",
    "outline": "大纲",
    "materials": "素材",
    "styles": "风格",
}

DECONSTRUCT_ANALYST = """你是「拆解人」，把一本小说拆成可复用的结构零件，而不是写书评。

工作原则：
1. 只看原文证据。每条设定、关系、事件都要能在给定文本里找到依据；找不到就不写。
2. 区分「作者做了什么」和「我觉得好不好」。前者是结构，后者是评价，只有前者能迁移。
3. 提炼技法时抹掉专有名词。输出的是「第三章用了一次身份误认制造反转」，
   而不是「主角张三在青云宗遇见了李四」。
4. 信息不足就留空，不要用常识补齐。宁缺毋滥。"""

LIMITS = {
    "identity": 1200,
    "persona": 4200,
    "domain": 3500,
    "user": 1600,
    "long": 2600,
    "project": 3600,
    "parent": 6000,
    "references": 6000,
    "skills": 1600,
    "runtime": 1200,
    # 审稿：只看「这一章写成了什么」，不看「写作意图」——后者会污染判断
    "reviewer": 3000,
    "rubric": 2200,
    "chapter": 16000,
    "prev_tail": 2000,
    "kb_digest": 5000,
    # 拆解：一次喂一组章节，输出结构由 schema 约束
    "analyst": 2600,
    "schema": 2000,
    "source": 24000,
}

LABELS = {
    "identity": "内核身份",
    "persona": "人格 / 专家",
    "domain": "域包规则",
    "user": "用户记忆",
    "long": "长期记忆",
    "project": "项目记忆",
    "parent": "主会话上下文",
    "references": "本轮引用",
    "skills": "技能索引",
    "runtime": "运行态",
    "reviewer": "审稿人设",
    "rubric": "审稿量表",
    "chapter": "本章正文",
    "prev_tail": "前情结尾",
    "kb_digest": "设定摘要",
    "analyst": "拆解人设",
    "schema": "输出结构",
    "source": "待拆解文本",
}

# 每种任务装哪些层。写稿用满 10 层；审稿刻意不带 persona / user / long /
# project / skills——审稿人要判断文本本身，而不是替作者找理由。
PROFILES: dict[str, tuple[str, ...]] = {
    "write": (
        "identity",
        "persona",
        "domain",
        "user",
        "long",
        "project",
        "parent",
        "references",
        "skills",
        "runtime",
    ),
    "review": (
        "identity",
        "reviewer",
        "rubric",
        "domain",
        "kb_digest",
        "prev_tail",
        "chapter",
        "references",
        "runtime",
    ),
    "deconstruct": ("identity", "analyst", "domain", "schema", "source", "runtime"),
}


def layers_for(profile: str) -> tuple[str, ...]:
    return PROFILES.get(profile, PROFILES["write"])


_WS = re.compile(r"\s+")

# 记忆是往文件尾部追加的：超预算时必须保留「最近写入」，否则新记忆永远
# 注入不进去，界面还显示已注入。
TAIL_LAYERS = {"user", "long", "project"}


def _clip_layer(text: str, limit: int, layer: str) -> str:
    if len(text) <= limit:
        return text
    if layer in TAIL_LAYERS:
        # 记忆是往尾部追加的：先保住标题行（通常是 "# 项目记忆"），
        # 剩下的预算按尾部回填，保证最近写进去的那几条一定在。
        head, sep, rest = text.partition("\n")
        head = f"{head}{sep}" if sep else ""
        if len(head) >= limit // 3:
            # 首行就吃掉了小半预算（没有标题的大段文本）：标题不要了，全部留给尾部
            head, rest = "", text
        keep = max(0, limit - len(head) - 12)
        if keep <= 0:
            return text[:limit]
        return f"{head}…（略）\n{rest[-keep:]}"
    return text[:limit]


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
    parent_messages: list[dict[str, Any]] | None = None,
) -> ContextBundle:
    """按层装配 system prompt，并产出可展示的注入清单。"""
    domain = domain or get_domain((session or {}).get("domain") or "book")
    memory.ensure_files(project)

    bundle = ContextBundle(
        system_prompt="", expert_id=(expert or {}).get("id", ""), domain_id=domain.id
    )
    blocks: list[str] = []

    def add(layer: str, title: str, source: str, text: str) -> None:
        text = (text or "").strip()
        limit = LIMITS[layer]
        included = bool(text)
        clipped = _clip_layer(text, limit, layer).rstrip() if included else ""
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

    add("identity", LABELS["identity"], "prompts/identity.md", prompts.read_layer("identity"))

    if expert:
        persona = _persona_block(expert)
        add("persona", f"专家 · {expert.get('name')}", expert.get("file", ""), persona)
    else:
        add(
            "persona",
            "默认人格",
            "prompts/persona.md",
            prompts.read_layer("persona", domain_id=domain.id),
        )

    add(
        "domain",
        f"域包 · {domain.name}",
        "prompts/domain.md",
        prompts.read_layer("domain", project, domain.id),
    )
    add("user", LABELS["user"], memory.memory_path("user").name, memory.read("user"))
    add("long", LABELS["long"], memory.memory_path("long").name, memory.read("long"))
    add(
        "project",
        LABELS["project"],
        "AGENTS.md",
        memory.read("project", project),
    )
    if parent_messages:
        add(
            "parent",
            LABELS["parent"],
            "主会话",
            _parent_block(parent_messages),
        )
    if references:
        add(
            "references",
            LABELS["references"],
            f"{len(references)} 项",
            _references_block(project, references),
        )
    add(
        "skills",
        LABELS["skills"],
        str(Path(domain.skills_subdir) / "*" / "SKILL.md"),
        _skills_index(project, domain),
    )

    runtime = _runtime_block(project, session, expert, readonly, builder)
    add("runtime", LABELS["runtime"], "runtime", runtime)

    bundle.system_prompt = "\n\n".join(blocks)
    bundle.total_chars = len(bundle.system_prompt)
    digest = hashlib.sha1(bundle.system_prompt.encode("utf-8")).hexdigest()[:12]
    bundle.fingerprint = f"{domain.id}:{bundle.expert_id or '-'}:{digest}"
    return bundle


def _make_adder(bundle: ContextBundle, blocks: list[str]):
    """按层预算裁剪并记账，返回可复用的 add()。审稿/拆解装配共用。"""

    def add(layer: str, title: str, source: str, text: str) -> None:
        text = (text or "").strip()
        limit = LIMITS[layer]
        included = bool(text)
        clipped = _clip_layer(text, limit, layer).rstrip() if included else ""
        truncated = included and len(text) > limit
        if truncated:
            clipped += "\n…（已按层预算截断）"
        bundle.items.append(
            ContextItem(
                layer=layer,
                title=title or LABELS[layer],
                source=source,
                chars=len(text),
                limit=limit,
                truncated=truncated,
                preview=_preview(clipped),
                included=included,
            )
        )
        if included:
            blocks.append(clipped)

    return add


def assemble_review(
    project: Path,
    *,
    chapter_title: str,
    chapter_text: str,
    prev_tail: str = "",
    references: list[dict[str, Any]] | None = None,
    note: str = "",
) -> ContextBundle:
    """审稿专用装配：设定摘要 + 前情 + 本章正文 + 量表。

    刻意不注入 persona / user / long / project / skills——写作意图与个人偏好
    会让审稿人替作者找理由。
    """
    domain = get_domain("book")
    bundle = ContextBundle(system_prompt="", expert_id="reviewer", domain_id=domain.id)
    blocks: list[str] = []
    add = _make_adder(bundle, blocks)

    add("identity", LABELS["identity"], "prompts/identity.md", prompts.read_layer("identity"))
    add("reviewer", LABELS["reviewer"], "builtin:reviewer", REVIEWER)
    add("rubric", LABELS["rubric"], "builtin:rubric", RUBRIC)
    add(
        "domain",
        f"域包 · {domain.name}",
        "prompts/domain.md",
        prompts.read_layer("domain", project, domain.id),
    )
    add("kb_digest", LABELS["kb_digest"], "kb/*", _kb_digest(project))
    if prev_tail.strip():
        add("prev_tail", LABELS["prev_tail"], "上一章结尾", prev_tail)
    add("chapter", f"本章 · {chapter_title}", chapter_title, chapter_text)
    if references:
        add(
            "references",
            LABELS["references"],
            f"{len(references)} 项",
            _references_block(project, references),
        )
    if note.strip():
        add("runtime", LABELS["runtime"], "runtime", note)

    bundle.system_prompt = "\n\n".join(blocks)
    bundle.total_chars = len(bundle.system_prompt)
    digest = hashlib.sha1(bundle.system_prompt.encode("utf-8")).hexdigest()[:12]
    bundle.fingerprint = f"review:{digest}"
    return bundle


def assemble_deconstruct(
    project: Path,
    *,
    source_text: str,
    schema: str,
    note: str = "",
) -> ContextBundle:
    """拆解专用装配：待拆文本 + 输出结构。同样不注入写作人设。"""
    domain = get_domain("book")
    bundle = ContextBundle(system_prompt="", expert_id="analyst", domain_id=domain.id)
    blocks: list[str] = []
    add = _make_adder(bundle, blocks)

    add("identity", LABELS["identity"], "prompts/identity.md", prompts.read_layer("identity"))
    add("analyst", LABELS["analyst"], "builtin:analyst", DECONSTRUCT_ANALYST)
    add(
        "domain",
        f"域包 · {domain.name}",
        "prompts/domain.md",
        prompts.read_layer("domain", project, domain.id),
    )
    add("schema", LABELS["schema"], "builtin:schema", schema)
    add("source", LABELS["source"], "source", source_text)
    if note.strip():
        add("runtime", LABELS["runtime"], "runtime", note)

    bundle.system_prompt = "\n\n".join(blocks)
    bundle.total_chars = len(bundle.system_prompt)
    digest = hashlib.sha1(bundle.system_prompt.encode("utf-8")).hexdigest()[:12]
    bundle.fingerprint = f"deconstruct:{digest}"
    return bundle


def _kb_digest(project: Path, per_kind: int = 12) -> str:
    """设定摘要：只给名字 + 一句话，不整卡注入——审稿看的是正文，不是设定原文。"""
    lines: list[str] = []
    for kind in KINDS:
        items = list_entities(project, kind)
        if not items:
            continue
        lines.append(f"## {KIND_LABELS.get(kind, kind)}")
        for item in items[:per_kind]:
            meta = item.get("meta") or {}
            summary = str(meta.get("summary") or meta.get("description") or "").strip()
            summary = _WS.sub(" ", summary)[:60]
            aliases = meta.get("aliases") or []
            alias_text = f"（别名：{'、'.join(str(a) for a in aliases)}）" if aliases else ""
            suffix = f"：{summary}" if summary else ""
            lines.append(f"- {item['title']}{alias_text}{suffix}")
        if len(items) > per_kind:
            lines.append(f"- …另有 {len(items) - per_kind} 条")
    return "\n".join(lines) or "（知识库还没有设定卡）"


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
            meta, body = parse_note(read_text(file))
            if meta.get("enabled") is False:
                continue
            name = meta.get("display_name") or meta.get("name") or file.parent.name
            description = meta.get("description") or _WS.sub(" ", body).strip()[:120]
            lines.append(f"- [{scope}] {name}（{file.parent.name}）：{description}")
    if not lines:
        return "（暂无技能。需要时可用 skill_write 创建。）"
    return "\n".join(lines)


def _parent_block(messages: list[dict[str, Any]]) -> str:
    """把主会话最近几轮只读注入侧问，让侧问知道当前在聊什么。

    侧问仍有独立 thread 与独立 checkpoint，这些消息不会写回主会话。
    """
    lines: list[str] = []
    for item in messages[-8:]:
        text = str(item.get("content") or "").strip()
        if not text:
            continue
        role = "用户" if item.get("role") == "user" else "助手"
        lines.append(f"**{role}**：{text[:2000]}")
    if not lines:
        return ""
    return (
        "以下是主会话最近的对话，只用于理解当前讨论背景。\n"
        "不要复述这些内容，也不要把自己当成这些回合的参与者。\n\n" + "\n\n".join(lines)
    )


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
                    blocks.append(f'<ref type="entity" name="{name}">未找到该条目</ref>')
                    continue
                progress = read_book_meta(project).get("progress") or {}
                meta = trim_meta(entity["meta"], int(progress.get("chapter") or 0))
                blocks.append(
                    f'<ref type="entity" name="{entity["title"]}" '
                    f'source="{entity["file"]}">\n'
                    f"{dump_note(meta, entity['body'])}\n</ref>"
                )
            elif kind in {"file", "chapter", "skill"}:
                path = str(ref.get("path") or "")
                target = safe_join(project, path)
                if not target.exists():
                    blocks.append(f'<ref type="{kind}" source="{path}">文件不存在</ref>')
                    continue
                relative = target.relative_to(project.resolve()).as_posix()
                if check_path(load_settings().sandbox, relative, "read") == "deny":
                    blocks.append(f'<ref type="{kind}" source="{path}">该路径不允许引用</ref>')
                    continue
                text = read_text(target)
                blocks.append(f'<ref type="{kind}" source="{path}">\n{_clip_ref(text)}\n</ref>')
        except (ValueError, OSError) as exc:
            blocks.append(f'<ref type="{kind}" name="{name}">引用失败：{exc}</ref>')
    return "\n\n".join(blocks) or "（引用为空）"


def _clip_ref(text: str, limit: int = 1500) -> str:
    """单个引用块的字符上限。

    整层预算只有 6000 字：如果单项给 4000，@ 两个长文件时第二个会被从中间腰斩。
    1500 × 最多 4 项正好落在预算内，每个引用都能带上开头与关键段落。
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n…（引用内容过长，已截断）"


def _stat_line(project: Path) -> str:
    try:
        stats = compute_stats(project)
    except Exception:  # noqa: BLE001 - 统计失败不该影响对话
        return "规模未知"
    if not stats.get("chapters"):
        return "还没有成稿"
    return f"{stats['chapters']} 章，约 {stats['words']} 字"


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
        f"进度：第{progress.get('volume', 1)}卷第{progress.get('chapter', 1)}章"
        f"（全书 {_stat_line(project)}）",
        f"项目目录：{project}",
    ]
    if session:
        lines.append(
            f"当前会话：{session.get('title') or '未命名'}（{session.get('kind') or 'main'}）"
        )
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


def tool_context(
    project: Path, *, project_id: str = "", session_id: str = "", readonly: bool = False
) -> ToolContext:
    from .config import load_settings

    settings = load_settings()
    return ToolContext(
        project=project,
        embedding=settings.embedding,
        project_id=project_id,
        session_id=session_id,
        readonly=readonly,
        sandbox=settings.sandbox,
    )
