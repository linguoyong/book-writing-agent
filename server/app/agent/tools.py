from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from ..config import EmbeddingSettings
from ..kb.repository import KINDS, get_entity, list_entities, save_entity
from ..kb.search import KbIndex
from ..workspace import git_diff, read_book_meta, safe_join

SYSTEM_PROMPT = """你是一名本地小说写作助手，工作在用户的书稿项目中。

工作原则：
1. 写正文前，先用 kb_search / kb_get 确认角色当前状态、势力关系、世界观设定，避免与既有设定冲突。
2. 角色状态按章节推进，只使用 chapter 不超过当前写作进度的状态。
3. 修改知识库或正文时，使用工具真实写入文件，不要只在回复里贴出内容。
4. 检索结果要注明出处（章节号或文件路径）。
5. 不确定的设定先向用户确认，不要自行编造并写入知识库。
6. 保持用户已有的写作风格；需要风格参考时检索 styles / materials。

当前写作进度由项目 book.json 的 progress 字段决定。
"""


def build_tools(project: Path, embedding: EmbeddingSettings, readonly: bool = False) -> list[Any]:
    index = KbIndex(project, embedding)

    def _ensure_index() -> None:
        if index.stats()["chunks"] == 0:
            index.rebuild()

    @tool
    def kb_search(
        query: str,
        kinds: list[str] | None = None,
        chapter_limit: int | None = None,
        top_k: int = 8,
    ) -> str:
        """检索知识库与原文。kinds 可选值：characters/factions/items/locations/world/outline/materials/styles/chapters。
        chapter_limit 用于限制只检索不超过该章节号的内容，避免剧透。返回带出处的片段列表。"""
        _ensure_index()
        results = index.search(
            query, kinds=kinds, chapter_limit=chapter_limit, top_k=top_k
        )
        if not results:
            return "未检索到相关内容。"
        lines = []
        for item in results:
            label = {
                "chapters": "原文",
                "characters": "角色",
                "factions": "势力",
                "items": "物品",
                "locations": "地点",
                "world": "世界观",
                "outline": "大纲",
                "materials": "素材",
                "styles": "风格",
            }.get(item["kind"], item["kind"])
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
        try:
            meta = json.loads(meta_json) if meta_json.strip() else {}
        except json.JSONDecodeError as exc:
            return f"meta_json 不是合法 JSON：{exc}"
        entity = save_entity(project, kind, entity_id, meta, body)
        index.rebuild()
        return f"已写入 {entity['file']}"

    @tool
    def project_overview() -> str:
        """查看当前书稿项目概况：书名、进度、知识库条目数、章节数。"""
        meta = read_book_meta(project)
        counts = {kind: len(list_entities(project, kind)) for kind in KINDS}
        chapters = sorted((project / "chapters").glob("*.md")) if (project / "chapters").exists() else []
        manuscript = sorted((project / "manuscript").rglob("*.md")) if (project / "manuscript").exists() else []
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
        candidate = directory / f"{chapter}.md"
        if not candidate.exists():
            matches = sorted(directory.glob(f"*{chapter}*.md"))
            if not matches:
                return f"未找到章节：{chapter}"
            candidate = matches[0]
        return candidate.read_text(encoding="utf-8")

    @tool
    def manuscript_read(path: str) -> str:
        """读取 manuscript 目录下的文稿文件。path 为相对 manuscript 的路径，例如 vol-01/ch-001.md。"""
        target = safe_join(project / "manuscript", path)
        if not target.exists():
            return f"文件不存在：{path}"
        return target.read_text(encoding="utf-8")

    @tool
    def manuscript_write(path: str, content: str, mode: str = "overwrite") -> str:
        """写入 manuscript 目录下的文稿。mode 为 overwrite 或 append。写入后不会自动提交 git。"""
        target = safe_join(project / "manuscript", path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append" and target.exists():
            existing = target.read_text(encoding="utf-8")
            target.write_text(existing + "\n\n" + content, encoding="utf-8")
        else:
            target.write_text(content, encoding="utf-8")
        return f"已写入 {target.relative_to(project)}"

    @tool
    def git_view_diff() -> str:
        """查看书稿项目当前未提交的改动。"""
        diff = git_diff(project)
        return diff[:12000] if diff.strip() else "当前没有未提交的改动。"

    readonly_tools = [
        kb_search,
        kb_get,
        kb_list,
        project_overview,
        chapter_list,
        chapter_read,
        manuscript_read,
        git_view_diff,
    ]
    if readonly:
        return readonly_tools
    return [*readonly_tools, kb_write, manuscript_write]
