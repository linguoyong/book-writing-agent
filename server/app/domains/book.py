from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from .. import db, memory
from ..experts import save_expert
from ..kb.repository import (
    KINDS,
    dump_note,
    get_entity,
    list_entities,
    parse_note,
    save_entity,
    state_at,
    trim_meta,
)
from ..kb.search import KbIndex, load_kb_config
from ..sandbox import check_path
from ..text import read_text, save_text
from ..workspace import git_diff, read_book_meta, safe_join, snapshot_file
from .base import ToolContext

RULES = """你工作在用户的书稿项目里，当前域是「长篇小说写作」。

工作原则：
1. 写正文前，先用 kb_search / kb_get 确认角色当前状态、势力关系、世界观设定，避免冲突。
2. 角色状态按章节推进，只使用 chapter 不超过当前写作进度的状态，避免剧透与状态错乱。
3. 修改知识库或正文时用工具真实写入文件，不要只在回复里贴出内容。
4. 检索结果要注明出处（章节号或文件路径）。
5. 不确定的设定先向用户确认，不要自行编造并写入知识库。
6. 保持用户已有的写作风格；需要参考时检索 styles / materials。

关于记忆：
- 用户说「记住」，或给出长期有效的偏好、设定决策时，调用 remember 写入。
- 回忆以前讨论过的事，用 recall_conversations 检索历史，不要凭印象编造。
- 记忆与当前用户要求冲突时，以用户当前要求为准。
"""

PERSONA = """你是一位长篇小说的写作与编辑搭档。你读得懂设定，改得动正文，也守得住一致性。
你说话直接，不吹捧；不确定的地方会先问，不猜着写。"""


def build_tools(ctx: ToolContext) -> list[Any]:
    project = ctx.project
    index = KbIndex(project, ctx.embedding)

    def _ensure_index() -> None:
        if not index.has_baseline():
            # 只补文本索引：向量编码可能跑几十秒，不能挂在一次工具调用里，
            # 由知识库页的后台重建补齐（界面上会提示向量缺失）
            index.rebuild(embed=False)

    def _deny(path: str) -> str | None:
        """路径规则 deny 是硬边界：完全访问模式下也不能写。"""
        if check_path(ctx.sandbox, path, "write") == "deny":
            return f"操作被路径规则禁止：{path}（write=deny）"
        return None

    @tool
    def kb_search(
        query: str,
        kinds: list[str] | None = None,
        chapter_limit: int | None = None,
        top_k: int | None = None,
    ) -> str:
        """检索知识库与原文。kinds 可选值：characters/factions/items/locations/world/outline/materials/styles/chapters。
        chapter_limit 用于限制只检索不超过该章节号的内容，避免剧透。返回带出处的片段列表。"""
        _ensure_index()
        # 知识库详情页「检索设置」写的是 kb/config.json：这里必须跟着走，
        # 否则页面上调的模式、权重、相关度阈值对 Agent 完全没有作用。
        config = load_kb_config(project)
        mode = str(config["mode"])
        if mode == "vector" and index.embedding.provider == "none":
            # 向量服务没开时选「仅向量」会一条都搜不到，静默失效比降级更糟
            mode = "keyword"
        results = index.search(
            query,
            kinds=kinds,
            chapter_limit=chapter_limit if chapter_limit is not None else config["chapter_limit"],
            top_k=top_k or int(config["top_k"]),
            threshold=float(config["threshold"]),
            mode=mode,
            alpha=float(config["alpha"]),
        )
        if not results:
            return "未检索到相关内容。"
        labels = {
            "chapters": "原文",
            "characters": "角色",
            "factions": "势力",
            "items": "物品",
            "locations": "地点",
            "world": "世界观",
            "outline": "大纲",
            "materials": "素材",
            "styles": "风格",
        }
        lines = []
        for item in results:
            label = labels.get(item["kind"], item["kind"])
            chapter = f"（第{item['chapter']}章）" if item["chapter"] else ""
            lines.append(
                f"[{label}] {item['title']}{chapter} · {item['source']}\n{item['text'][:900]}"
            )
        return "\n\n---\n\n".join(lines)

    @tool
    def kb_get(kind: str, entity_id: str) -> str:
        """读取单个知识库条目的完整内容。kind 取值同 kb_search 的知识库类型。"""
        entity = get_entity(project, kind, entity_id)
        if not entity:
            return f"未找到条目：{kind}/{entity_id}"
        # 防剧透：timeline 只给到当前写作进度，并直接给出「当前状态」
        progress = read_book_meta(project).get("progress") or {}
        chapter = int(progress.get("chapter") or 0)
        if chapter:
            entity = dict(entity)
            entity["meta"] = trim_meta(entity.get("meta") or {}, chapter)
            current = state_at(entity["meta"], chapter)
            if current:
                entity["current_state"] = current
        return json.dumps(entity, ensure_ascii=False, indent=2)

    @tool
    def kb_list(kind: str) -> str:
        """列出某类知识库的全部条目（id、名称、标签）。"""
        entities = list_entities(project, kind)
        brief = [
            {
                "id": item["id"],
                "title": item["title"],
                "tags": item["meta"].get("tags", []),
                "file": item["file"],
            }
            for item in entities
        ]
        return json.dumps(brief, ensure_ascii=False, indent=2)

    @tool
    def kb_write(kind: str, entity_id: str, meta_json: str, body: str) -> str:
        """新增或更新知识库条目。kind 必须是 characters/factions/items/locations/world/outline/materials/styles 之一。
        meta_json 是 JSON 对象字符串，例如 {"name": "林昭", "aliases": ["小林"], "timeline": [...]}。
        body 是 Markdown 正文。写入后不会自动提交 git。"""
        if kind not in KINDS:
            return f"非法 kind：{kind}"
        denied = _deny(f"kb/{kind}/{entity_id}.md")
        if denied:
            return denied
        try:
            meta = json.loads(meta_json) if meta_json.strip() else {}
        except json.JSONDecodeError as exc:
            return f"meta_json 不是合法 JSON：{exc}"
        entity = save_entity(project, kind, entity_id, meta, body)
        index.reindex_entity(kind, str(entity["id"]))
        return f"已写入 {entity['file']}"

    @tool
    def project_overview() -> str:
        """查看当前书稿项目概况：书名、进度、知识库条目数、章节数。"""
        meta = read_book_meta(project)
        counts = {kind: len(list_entities(project, kind)) for kind in KINDS}
        chapters_dir = project / "chapters"
        manuscript_dir = project / "manuscript"
        chapters = sorted(chapters_dir.glob("*.md")) if chapters_dir.exists() else []
        manuscript = sorted(manuscript_dir.rglob("*.md")) if manuscript_dir.exists() else []
        return json.dumps(
            {
                "book": meta,
                "kb_counts": counts,
                "chapter_count": len(chapters),
                "manuscript_files": [str(p.relative_to(project)) for p in manuscript[:50]],
            },
            ensure_ascii=False,
            indent=2,
        )

    @tool
    def chapter_list() -> str:
        """列出已导入的章节文件及编号。"""
        directory = project / "chapters"
        if not directory.exists():
            return "尚未导入章节。"
        files = sorted(directory.glob("*.md"))
        return "\n".join(f"- {p.stem}（{p.stat().st_size} 字节）" for p in files[:200])

    @tool
    def chapter_read(chapter: str) -> str:
        """读取一个章节的正文。chapter 可传章节文件名（不含 .md）或章节号。"""
        directory = project / "chapters"
        name = str(chapter).strip().replace("\\", "/").split("/")[-1]
        if not name or name in {".", ".."}:
            return "非法的章节名"
        candidate = directory / f"{name}.md"
        if not candidate.exists():
            matches = sorted(directory.glob(f"*{name}*.md"))
            if not matches:
                return f"未找到章节：{chapter}"
            candidate = matches[0]
        return read_text(candidate)

    @tool
    def manuscript_read(path: str) -> str:
        """读取 manuscript 目录下的文稿文件。path 为相对 manuscript 的路径，例如 vol-01/ch-001.md。"""
        target = safe_join(project / "manuscript", path)
        if not target.exists():
            return f"文件不存在：{path}"
        return read_text(target)

    @tool
    def manuscript_write(path: str, content: str, mode: str = "overwrite") -> str:
        """写入 manuscript 目录下的文稿。mode 为 overwrite 或 append。写入后不会自动提交 git。"""
        denied = _deny(f"manuscript/{path}")
        if denied:
            return denied
        try:
            target = safe_join(project / "manuscript", path)
        except ValueError:
            return "路径越界"
        target.parent.mkdir(parents=True, exist_ok=True)
        # 覆盖前留一份旧内容到 .index/history：进程被杀、误覆盖时还能捞回来
        snapshot_file(project, target)
        if mode == "append" and target.exists():
            existing = read_text(target)
            save_text(target, existing + "\n\n" + content)
        else:
            save_text(target, content)
        # 正文变了，旧审稿结论就失效了：保留分数供参考，状态降为 stale
        _mark_stale(target)
        return f"已写入 {target.relative_to(project)}"

    @tool
    def lint_consistency() -> str:
        """跑一遍一致性体检：角色别称混用、未回收伏笔、时间线倒退、疑似未登记角色。
        写完一章或改完设定后主动跑一次，把发现的问题报给用户。"""
        from ..kb.lint import lint_project

        report = lint_project(project)
        stats = report["stats"]
        issues = report["issues"]
        if not issues:
            return (
                f"体检通过：{stats['chapters']} 章 / {stats['characters']} 个角色，"
                "没有发现别称混用、未回收伏笔、时间线倒退或疑似漏登记的角色。"
            )
        lines = [
            f"体检完成：{stats['chapters']} 章 / {stats['characters']} 个角色，"
            f"{stats['warn']} 个警告、{stats['info']} 个提示。"
        ]
        for issue in issues:
            where = f"[{issue['chapter']}]" if issue["chapter"] else ""
            level = "警告" if issue["severity"] == "warn" else "提示"
            lines.append(f"- {level}{where} {issue['message']}")
        return "\n".join(lines)

    @tool
    def git_view_diff() -> str:
        """查看书稿项目当前未提交的改动。"""
        diff = git_diff(project)
        return diff[:12000] if diff.strip() else "当前没有未提交的改动。"

    @tool
    def chapter_review(chapter: str, note: str = "") -> str:
        """审阅一章正文，返回问题清单（P0 必改 / P1 应改 / P2 可打磨）与六维评分。
        chapter 可以是路径（vol-01/ch-003.md）或章号（3）。
        审稿只评判不改稿；结论写回本章 front-matter，明细存 .index/reviews。
        写完一章后主动调用它，拿到问题先改 P0，再改 P1，改完再审一次。
        note 可选：告诉审稿人这次重点关注什么（例如「只看节奏与钩子」）。"""
        from ..review import ReviewError, run_review

        try:
            result = run_review(
                project,
                chapter,
                project_id=ctx.project_id,
                session_id=ctx.session_id,
                note=note,
            )
        except ReviewError as exc:
            return f"审稿失败：{exc}"
        return result.brief()

    @tool
    def review_status() -> str:
        """查看本书各章的审稿状态（未审 / 未通过 / 已通过）与最近一次分数。"""
        from ..review import list_reviews

        items = list_reviews(project)
        if not items:
            return "这本书还没有正文章节。"
        labels = {"pass": "已通过", "fail": "未通过", "draft": "未审"}
        lines = []
        for item in items:
            state = labels.get(str(item["status"]), str(item["status"]))
            score = f"，{item['score']} 分" if item.get("score") else ""
            round_no = item.get("round") or 0
            lines.append(
                f"- {item['chapter']}《{item['title']}》{state}"
                f"（第 {round_no} 轮{score}，{item['words']} 字）"
            )
        return "\n".join(lines)

    @tool
    def deconstruct_source(path: str, groups: int = 3, create_expert: bool = False) -> str:
        """拆解一部成品小说（.txt / .md），把设定写进知识库、把技法写成素材卡。
        path 为源文件路径（绝对路径或项目内相对路径）；groups 是拆几组，每组 3 章，
        默认只拆 3 组先看效果。create_expert=True 会额外生成一个拆解专家和技能。
        只在用户明确要求「拆书 / 对标某本作品」时调用，不要自动拆正在写的书。"""
        from pathlib import Path as SourcePath

        from ..deconstruct import DeconstructError
        from ..deconstruct import run as run_deconstruct

        source = SourcePath(path).expanduser()
        if not source.is_absolute():
            source = project / source
        try:
            result = run_deconstruct(
                project,
                source,
                max_groups=max(0, int(groups)),
                create_expert=create_expert,
                project_id=ctx.project_id,
            )
        except DeconstructError as exc:
            return f"拆解失败：{exc}"
        lines = [
            f"拆解完成：{result['groups']} 组 / {result['chapters']} 章，"
            f"新增实体 {result['entities']} 个，技法 {result['techniques']} 条"
        ]
        if result.get("expert"):
            lines.append(f"已生成专家：{result['expert']['name']}（可在专家页选中）")
        if result.get("expert_error"):
            lines.append(f"专家生成失败：{result['expert_error']}")
        if result.get("failed"):
            lines.append(f"{result['failed']} 组失败，可调小 groups 后重试")
        return "\n".join(lines)

    @tool
    def remember(text: str, scope: str = "long") -> str:
        """写入一条长期记忆。scope：user（用户偏好，跨项目）/ project（本项目约定，写入 AGENTS.md）/ long（其他长期事实，默认）。
        只记长期有效的信息：偏好、设定决策、结论、禁忌。不要记临时任务或寒暄。"""
        if scope not in {"user", "project", "long"}:
            return f"非法 scope：{scope}"
        line = memory.append(scope, text, project, source=f"session:{ctx.session_id}")
        if not line:
            return "该记忆已存在，未重复写入。"
        memory.daily_log(f"记住：{text[:120]}", tag="memory")
        title = {"user": "用户记忆", "project": "项目记忆", "long": "长期记忆"}[scope]
        return f"已写入{title}：{text}"

    @tool
    def recall_conversations(query: str, limit: int = 8) -> str:
        """回忆历史会话。当用户提到「之前说过」「上次定的」时，先用它检索，不要凭空猜。
        返回命中的历史消息片段与所属会话。"""
        hits = db.search_messages(query, limit=limit, project_id=ctx.project_id or None)
        if not hits:
            return "没有找到相关的历史记录。"
        lines = [
            f"[{item['session_title']} · {item['created_at'][:10]}] "
            f"{'用户' if item['role'] == 'user' else '助手'}：{item['content'][:400]}"
            for item in hits
        ]
        return "\n\n".join(lines)

    @tool
    def expert_write(
        expert_id: str,
        name: str,
        description: str,
        tags: str,
        prompt: str,
        body: str,
        skills: str = "",
    ) -> str:
        """创建或更新一个写作专家。expert_id 用简短的英文/拼音标识，name 为中文名，
        description 说明「什么时候该用这个专家」（用于激活判定），tags 用逗号分隔，
        prompt 是注入模型的写作风格指令，body 是 Markdown 正文，写清工作流程与禁忌。
        skills 是逗号分隔的技能目录名，声明该专家启动时预加载的技能。"""
        saved = save_expert(
            project,
            expert_id,
            {
                "name": name,
                "description": description,
                "tags": [
                    item.strip() for item in tags.replace("，", ",").split(",") if item.strip()
                ],
                "avatar": name[:1] if name else "专",
                "prompt": prompt,
                "skills": [
                    item.strip() for item in skills.replace("，", ",").split(",") if item.strip()
                ],
            },
            body,
        )
        return f"已保存专家 {saved['name']}：{saved['file']}"

    @tool
    def skill_write(name: str, description: str, instructions: str, slug: str = "") -> str:
        """创建一个技能，写入 skills/<slug>/SKILL.md。
        name 为技能中文名，slug 为目录名（小写英文与连字符，留空则自动生成），
        description 一句话说明用途（用于渐进披露时的索引），instructions 是 Markdown 执行步骤与输出要求。"""
        if not name.strip():
            return "技能名不能为空"
        directory_name = _slugify(slug or name)
        directory = project / "skills" / directory_name
        directory.mkdir(parents=True, exist_ok=True)
        file = directory / "SKILL.md"
        meta = {
            "name": directory_name,
            "display_name": name.strip(),
            "description": description.strip(),
            "enabled": True,
        }
        save_text(file, dump_note(meta, instructions))
        return f"已创建技能 {name}：{file.relative_to(project)}"

    readonly_tools = [
        kb_search,
        kb_get,
        kb_list,
        project_overview,
        chapter_list,
        chapter_read,
        manuscript_read,
        lint_consistency,
        git_view_diff,
        recall_conversations,
        review_status,
    ]
    if ctx.readonly:
        return readonly_tools
    return [
        *readonly_tools,
        chapter_review,
        deconstruct_source,
        kb_write,
        manuscript_write,
        remember,
        expert_write,
        skill_write,
    ]


def _mark_stale(target: Path) -> None:
    """正文被改写后把「已通过」降级为待重审。fail 本来就是待改，不动。"""
    try:
        meta, body = parse_note(read_text(target))
    except OSError:
        return
    review = meta.get("review")
    if not isinstance(review, dict) or review.get("status") != "pass":
        return
    review["status"] = "stale"
    review["stale_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    meta["review"] = review
    try:
        save_text(target, dump_note(meta, body))
    except OSError:
        pass


def _slugify(value: str) -> str:
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    if ascii_part:
        return ascii_part
    # 中文名无法直接作为目录名（技能规范要求 ASCII），退化为稳定短标识
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:6]
    return f"skill-{digest}"


class BookDomain:
    id = "book"
    name = "长篇小说写作"
    description = "书稿项目：角色/势力/物品/世界观/大纲/素材 + 章节原文，支持检索、写作与一致性维护"
    persona = PERSONA
    rules = RULES
    skills_subdir = "skills"

    def build_tools(self, ctx: ToolContext) -> list[Any]:
        return build_tools(ctx)
