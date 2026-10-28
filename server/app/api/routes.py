from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import db, memory
from ..agent.checkpointer import drop_thread
from ..agent.factory import resolve_expert
from ..agent.runner import approve_stream, chat_stream
from ..agent import steering
from ..config import load_settings, save_settings
from ..context import assemble
from ..domains import list_domains
from ..experts import delete_expert, get_expert, list_experts, save_expert
from ..kb.repository import (
    KINDS,
    delete_entity,
    get_entity,
    list_entities,
    parse_note,
    save_entity,
)
from ..kb.search import KbIndex, load_kb_config, save_kb_config
from ..workspace import (
    create_book,
    default_project_path,
    git_diff,
    git_status,
    read_book_meta,
    safe_join,
    write_book_meta,
)

router = APIRouter()

TREE_ROOTS = ("manuscript", "chapters", "kb")
HIDDEN_PARTS = {".git", ".index", "node_modules", "__pycache__"}


# ---------------------------------------------------------------- 配置


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/config")
def get_config() -> dict[str, Any]:
    return load_settings().model_dump()


@router.put("/config")
def put_config(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    merged = settings.model_dump()
    for key in ("writer", "extractor", "embedding", "sandbox"):
        if key in payload and isinstance(payload[key], dict):
            merged[key].update(payload[key])
    save_settings(type(settings).model_validate(merged))
    return load_settings().model_dump()


# ---------------------------------------------------------------- 项目


class CreateProjectRequest(BaseModel):
    name: str
    title: str = ""
    author: str = ""
    path: str = ""


@router.get("/projects")
def get_projects() -> list[dict[str, Any]]:
    projects = db.list_projects()
    for project in projects:
        path = Path(project["path"])
        project["exists"] = path.exists()
    return projects


@router.post("/projects")
def post_project(req: CreateProjectRequest) -> dict[str, Any]:
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="项目名不能为空")
    path = create_book(req.name, req.title, req.author, req.path)
    existing = next((p for p in db.list_projects() if p["path"] == str(path)), None)
    if existing:
        return {**existing, "meta": read_book_meta(path)}
    project = db.create_project(req.name, str(path))
    return {**project, "meta": read_book_meta(path)}


@router.get("/projects/default-path")
def get_default_path(name: str = "未命名") -> dict[str, str]:
    """新建书稿的默认落点：~/.book-agent/books/<slug>。"""
    return {"path": str(default_project_path(name))}


class OpenProjectRequest(BaseModel):
    path: str


@router.post("/projects/open")
def open_project(req: OpenProjectRequest) -> dict[str, Any]:
    target = Path(req.path).expanduser()
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=400, detail=f"目录不存在：{target}")
    path = target.resolve()
    existing = next(
        (p for p in db.list_projects() if Path(p["path"]).resolve() == path), None
    )
    if existing:
        return {**existing, "meta": read_book_meta(path)}
    meta = read_book_meta(path)
    name = path.name or meta.get("title") or "未命名空间"
    created = create_book(name, meta.get("title") or name, meta.get("author") or "", str(path))
    project = db.create_project(name, str(created))
    return {**project, "meta": read_book_meta(created)}


@router.get("/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    path = Path(project["path"])
    return {
        **project,
        "exists": path.exists(),
        "meta": read_book_meta(path) if path.exists() else {},
    }


@router.get("/projects/{project_id}/overview")
def project_overview(project_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    path = Path(project["path"])
    counts = {kind: len(list_entities(path, kind)) for kind in KINDS}
    chapters = sorted((path / "chapters").glob("*.md")) if (path / "chapters").exists() else []
    manuscript = (
        sorted((path / "manuscript").rglob("*.md"))
        if (path / "manuscript").exists()
        else []
    )
    index = KbIndex(path, load_settings().embedding)
    return {
        "book": read_book_meta(path),
        "kb_counts": counts,
        "chapter_count": len(chapters),
        "manuscript_count": len(manuscript),
        "index": index.stats(),
        "git_dirty": bool(git_status(path).strip()),
    }


# ---------------------------------------------------------------- 会话


class CreateSessionRequest(BaseModel):
    title: str = "新会话"
    kind: str = "main"
    expert_id: str | None = None
    domain: str | None = "book"
    permission_mode: str | None = None


class SessionPatch(BaseModel):
    title: str | None = None
    expert_id: str | None = None
    domain: str | None = None
    permission_mode: str | None = None


@router.get("/projects/{project_id}/sessions")
def get_sessions(project_id: str) -> list[dict[str, Any]]:
    _require_project(project_id)
    return db.list_sessions(project_id)


@router.post("/projects/{project_id}/sessions")
def post_session(project_id: str, req: CreateSessionRequest) -> dict[str, Any]:
    _require_project(project_id)
    return db.create_session(
        project_id,
        req.title,
        req.kind,
        req.expert_id,
        req.domain,
        req.permission_mode,
    )


@router.patch("/sessions/{session_id}")
def patch_session(session_id: str, req: SessionPatch) -> dict[str, Any]:
    if not db.get_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    updated = db.update_session(session_id, **req.model_dump(exclude_none=True))
    assert updated is not None
    return updated


@router.get("/sessions/{session_id}/context")
def session_context(session_id: str) -> dict[str, Any]:
    """查看当前会话实际会注入的上下文（分层 + 预算 + 预览）。"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    project = _require_project(session["project_id"])
    path = Path(project["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="项目目录不存在")
    expert = resolve_expert(path, session.get("expert_id") or "general")
    bundle = assemble(
        path,
        session=session,
        expert=expert,
        readonly=session.get("kind") == "side",
    )
    return bundle.to_dict()


@router.get("/sessions/{session_id}/messages")
def get_messages(session_id: str) -> list[dict[str, Any]]:
    if not db.get_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return db.list_messages(session_id)


@router.delete("/sessions/{session_id}")
async def remove_session(session_id: str) -> dict[str, bool]:
    db.delete_session(session_id)
    await drop_thread(session_id)
    return {"ok": True}


# ---------------------------------------------------------------- 对话


class ChatRequest(BaseModel):
    session_id: str
    message: str
    mode: str = "main"
    expert_id: str | None = None
    references: list[dict[str, Any]] | None = None


@router.post("/chat")
async def post_chat(req: ChatRequest) -> StreamingResponse:
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")
    return StreamingResponse(
        chat_stream(
            req.session_id, req.message, req.mode, req.expert_id, req.references
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class Decision(BaseModel):
    type: str
    message: str | None = None


class ApproveRequest(BaseModel):
    session_id: str
    decisions: list[Decision]


@router.post("/chat/approve")
async def post_approve(req: ApproveRequest) -> StreamingResponse:
    decisions = [item.model_dump(exclude_none=True) for item in req.decisions]
    return StreamingResponse(
        approve_stream(req.session_id, decisions),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions/{session_id}/pending")
def get_pending(session_id: str) -> dict[str, Any]:
    if not db.get_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"approval": db.pending_approval(session_id)}


class SteerRequest(BaseModel):
    session_id: str
    message: str


@router.post("/chat/steer")
def post_steer(req: SteerRequest) -> dict[str, Any]:
    """执行中插入引导：不打断当前 run，模型下一步会看到这条指示。"""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="引导内容不能为空")
    if not db.get_session(req.session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    if not (steering.is_running(req.session_id) or db.pending_approval(req.session_id)):
        raise HTTPException(status_code=409, detail="当前没有进行中的对话")
    db.add_message(req.session_id, "user", req.message, meta={"steering": True})
    queued = steering.enqueue(req.session_id, req.message)
    return {"ok": True, "queued": queued}


@router.get("/sessions/{session_id}/approvals")
def get_approvals(session_id: str) -> list[dict[str, Any]]:
    return db.approval_history(session_id)


# ---------------------------------------------------------------- 引用候选


@router.get("/projects/{project_id}/reference-candidates")
def reference_candidates(
    project_id: str, q: str = "", limit: int = 20
) -> dict[str, Any]:
    project = _require_project(project_id)
    root = Path(project["path"])
    keyword = q.strip().lower()
    items: list[dict[str, Any]] = []

    for kind in KINDS:
        for entity in list_entities(root, kind):
            haystack = f"{entity['title']} {entity['id']} {' '.join(map(str, entity['meta'].get('tags') or []))}".lower()
            if keyword and keyword not in haystack:
                continue
            items.append(
                {
                    "type": "entity",
                    "kind": kind,
                    "id": entity["id"],
                    "name": entity["title"],
                    "path": entity["file"],
                    "hint": KB_KIND_NAMES.get(kind, kind),
                    "score": 2 if entity["title"].lower().startswith(keyword) else 1,
                }
            )

    for sub, ref_type, hint in (
        ("manuscript", "file", "文稿"),
        ("chapters", "chapter", "章节"),
    ):
        directory = root / sub
        if not directory.exists():
            continue
        for file in sorted(directory.rglob("*.md"))[:800]:
            relative = str(file.relative_to(root)).replace("\\", "/")
            if keyword and keyword not in relative.lower():
                continue
            items.append(
                {
                    "type": ref_type,
                    "name": file.stem,
                    "path": relative,
                    "hint": hint,
                    "score": 1,
                }
            )

    skills_dir = root / "skills"
    if skills_dir.exists():
        for file in sorted(skills_dir.glob("*/SKILL.md")):
            meta, _ = parse_note(file.read_text(encoding="utf-8"))
            name = meta.get("display_name") or meta.get("name") or file.parent.name
            if keyword and keyword not in f"{name} {file.parent.name}".lower():
                continue
            items.append(
                {
                    "type": "skill",
                    "name": str(name),
                    "path": str(file.relative_to(root)).replace("\\", "/"),
                    "hint": "技能",
                    "score": 1,
                }
            )

    items.sort(key=lambda item: (-int(item.get("score", 0)), item["name"]))
    return {"items": items[:limit]}


# ---------------------------------------------------------------- 内核：域包与记忆


@router.get("/domains")
def get_domains() -> list[dict[str, str]]:
    return list_domains()


class MemoryWrite(BaseModel):
    content: str
    project_id: str | None = None


@router.get("/memory")
def get_memory(project_id: str | None = None) -> dict[str, Any]:
    project = Path(_require_project(project_id)["path"]) if project_id else None
    memory.ensure_files(project)
    scope_names = ["user", "long"] + (["project"] if project else [])
    scopes = {scope: memory.read(scope, project) for scope in scope_names}
    entries = {scope: memory.entries(scope, project) for scope in scope_names}

    source_ids = {
        item["source"].split(":", 1)[1]
        for items in entries.values()
        for item in items
        if item.get("source", "").startswith("session:")
    }
    sources = {sid: title for sid, title in db.session_titles(list(source_ids)).items()}
    return {
        "status": memory.status(project),
        "scopes": scopes,
        "entries": entries,
        "sources": sources,
    }


class MemoryDelete(BaseModel):
    scope: str
    text: str
    project_id: str | None = None


@router.post("/memory/delete")
def delete_memory_entry(req: MemoryDelete) -> dict[str, bool]:
    if req.scope not in {"user", "long", "project"}:
        raise HTTPException(status_code=400, detail=f"未知记忆范围：{req.scope}")
    project = Path(_require_project(req.project_id)["path"]) if req.project_id else None
    if req.scope == "project" and project is None:
        raise HTTPException(status_code=400, detail="项目记忆需要 project_id")
    if not memory.delete_entry(req.scope, req.text, project):
        raise HTTPException(status_code=404, detail="未找到该记忆条目")
    return {"ok": True}


@router.put("/memory/{scope}")
def put_memory(scope: str, req: MemoryWrite) -> dict[str, Any]:
    if scope not in {"user", "long", "project"}:
        raise HTTPException(status_code=400, detail=f"未知记忆范围：{scope}")
    project = Path(_require_project(req.project_id)["path"]) if req.project_id else None
    if scope == "project" and project is None:
        raise HTTPException(status_code=400, detail="项目记忆需要 project_id")
    return memory.write(scope, req.content, project)


@router.post("/sessions/{session_id}/distill")
def distill(session_id: str) -> dict[str, Any]:
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    project = Path(_require_project(session["project_id"])["path"])
    try:
        return memory.distill_session(session_id, project)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"沉淀失败：{exc}") from exc


# ---------------------------------------------------------------- 知识库


class EntityRequest(BaseModel):
    id: str
    meta: dict[str, Any] = Field(default_factory=dict)
    body: str = ""


@router.get("/projects/{project_id}/kb/{kind}")
def get_entities(project_id: str, kind: str) -> list[dict[str, Any]]:
    project = _require_project(project_id)
    _require_kind(kind)
    return list_entities(Path(project["path"]), kind)


@router.post("/projects/{project_id}/kb/{kind}")
def post_entity(project_id: str, kind: str, req: EntityRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    _require_kind(kind)
    saved = save_entity(Path(project["path"]), kind, req.id, req.meta, req.body)
    return saved


@router.get("/projects/{project_id}/kb/{kind}/{entity_id}")
def get_entity_detail(project_id: str, kind: str, entity_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    _require_kind(kind)
    entity = get_entity(Path(project["path"]), kind, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="条目不存在")
    return entity


@router.put("/projects/{project_id}/kb/{kind}/{entity_id}")
def put_entity(
    project_id: str, kind: str, entity_id: str, req: EntityRequest
) -> dict[str, Any]:
    project = _require_project(project_id)
    _require_kind(kind)
    return save_entity(Path(project["path"]), kind, entity_id, req.meta, req.body)


@router.delete("/projects/{project_id}/kb/{kind}/{entity_id}")
def remove_entity(project_id: str, kind: str, entity_id: str) -> dict[str, bool]:
    project = _require_project(project_id)
    _require_kind(kind)
    return {"ok": delete_entity(Path(project["path"]), kind, entity_id)}


class SearchRequest(BaseModel):
    query: str
    kinds: list[str] | None = None
    chapter_limit: int | None = None
    top_k: int = 8
    threshold: float = 0.0
    mode: str = "hybrid"
    alpha: float = 0.5


@router.post("/projects/{project_id}/search")
def search_kb(project_id: str, req: SearchRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    index = KbIndex(Path(project["path"]), load_settings().embedding)
    results = index.search(
        req.query,
        kinds=req.kinds,
        chapter_limit=req.chapter_limit,
        top_k=req.top_k,
        threshold=req.threshold,
        mode=req.mode,
        alpha=req.alpha,
    )
    return {"query": req.query, "results": results}


@router.post("/projects/{project_id}/reindex")
def reindex_kb(project_id: str) -> dict[str, int]:
    project = _require_project(project_id)
    index = KbIndex(Path(project["path"]), load_settings().embedding)
    return index.rebuild()


# ---------------------------------------------------------------- 知识库扩展

KB_KIND_NAMES = {
    "characters": "角色",
    "factions": "势力",
    "items": "物品",
    "locations": "地点",
    "world": "世界观",
    "outline": "大纲",
    "materials": "素材",
    "styles": "风格",
}


@router.get("/projects/{project_id}/knowledge-bases")
def knowledge_bases(project_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    path = Path(project["path"])
    index = KbIndex(path, load_settings().embedding)
    counts = {kind: len(list_entities(path, kind)) for kind in KINDS}
    chunk_stats = index.stats_by_kind()
    if sum(counts.values()) > 0 and sum(chunk_stats.values()) == 0:
        index.rebuild()
        chunk_stats = index.stats_by_kind()
    return {
        "index": index.stats(),
        "config": load_kb_config(path),
        "items": [
            {
                "kind": kind,
                "name": KB_KIND_NAMES[kind],
                "count": counts[kind],
                "chunks": chunk_stats.get(kind, 0),
            }
            for kind in KINDS
        ],
    }


@router.get("/projects/{project_id}/chunks")
def list_chunks(
    project_id: str,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
    q: str | None = None,
) -> dict[str, Any]:
    project = _require_project(project_id)
    index = KbIndex(Path(project["path"]), load_settings().embedding)
    if index.stats()["chunks"] == 0:
        index.rebuild()
    return index.list_chunks(kind, limit, offset, q)


class KbConfigRequest(BaseModel):
    top_k: int = 8
    threshold: float = 0.0
    mode: str = "hybrid"
    alpha: float = 0.5
    chapter_limit: int | None = None


@router.get("/projects/{project_id}/kb-config")
def get_kb_config(project_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    return load_kb_config(Path(project["path"]))


@router.put("/projects/{project_id}/kb-config")
def put_kb_config(project_id: str, req: KbConfigRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    return save_kb_config(Path(project["path"]), req.model_dump())


# ---------------------------------------------------------------- 技能


@router.get("/projects/{project_id}/skills")
def list_skills(project_id: str) -> list[dict[str, Any]]:
    project = _require_project(project_id)
    root = Path(project["path"]) / "skills"
    root.mkdir(parents=True, exist_ok=True)
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for file in sorted(root.glob("*/SKILL.md")):
        meta, body = parse_note(file.read_text(encoding="utf-8"))
        items.append(
            {
                "name": meta.get("name") or file.parent.name,
                "description": meta.get("description") or body.strip()[:200],
                "path": str(file.relative_to(Path(project["path"]))),
                "enabled": bool(meta.get("enabled", True)),
            }
        )
    return items


# ---------------------------------------------------------------- 专家


class ExpertRequest(BaseModel):
    id: str
    meta: dict[str, Any] = Field(default_factory=dict)
    body: str = ""


@router.get("/projects/{project_id}/experts")
def get_experts(project_id: str) -> list[dict[str, Any]]:
    project = _require_project(project_id)
    return list_experts(Path(project["path"]))


@router.post("/projects/{project_id}/experts")
def post_expert(project_id: str, req: ExpertRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    return save_expert(Path(project["path"]), req.id, req.meta, req.body)


@router.put("/projects/{project_id}/experts/{expert_id}")
def put_expert(project_id: str, expert_id: str, req: ExpertRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    return save_expert(Path(project["path"]), expert_id, req.meta, req.body)


@router.delete("/projects/{project_id}/experts/{expert_id}")
def remove_expert(project_id: str, expert_id: str) -> dict[str, bool]:
    project = _require_project(project_id)
    return {"ok": delete_expert(Path(project["path"]), expert_id)}


# ---------------------------------------------------------------- 文件


@router.get("/projects/{project_id}/tree")
def get_tree(project_id: str) -> list[dict[str, Any]]:
    project = _require_project(project_id)
    root = Path(project["path"])
    return [
        _tree_node(root, root / name)
        for name in TREE_ROOTS
        if (root / name).exists()
    ]


@router.get("/projects/{project_id}/file")
def read_file(project_id: str, path: str) -> dict[str, Any]:
    project = _require_project(project_id)
    root = Path(project["path"])
    target = safe_join(root, path)
    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="文件不存在")
    return {"path": path, "content": target.read_text(encoding="utf-8")}


class WriteFileRequest(BaseModel):
    path: str
    content: str


@router.put("/projects/{project_id}/file")
def write_file(project_id: str, req: WriteFileRequest) -> dict[str, bool]:
    project = _require_project(project_id)
    root = Path(project["path"])
    target = safe_join(root, req.path)
    if any(part in HIDDEN_PARTS for part in target.relative_to(root).parts):
        raise HTTPException(status_code=400, detail="该路径不允许写入")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(req.content, encoding="utf-8")
    return {"ok": True}


# ---------------------------------------------------------------- git


@router.get("/projects/{project_id}/git/status")
def get_git_status(project_id: str) -> dict[str, str]:
    project = _require_project(project_id)
    return {"status": git_status(Path(project["path"]))}


@router.get("/projects/{project_id}/git/diff")
def get_git_diff(project_id: str) -> dict[str, str]:
    project = _require_project(project_id)
    return {"diff": git_diff(Path(project["path"]))}


# ---------------------------------------------------------------- 工具


def _require_project(project_id: str) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _require_kind(kind: str) -> None:
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"未知知识库类型: {kind}")


def _tree_node(root: Path, path: Path) -> dict[str, Any]:
    node: dict[str, Any] = {
        "name": path.name,
        "path": str(path.relative_to(root)).replace("\\", "/"),
        "type": "dir" if path.is_dir() else "file",
    }
    if path.is_dir():
        children = []
        for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name)):
            if child.name in HIDDEN_PARTS:
                continue
            children.append(_tree_node(root, child))
        node["children"] = children
    return node
