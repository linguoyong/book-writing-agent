from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import db
from ..agent.runner import chat_stream
from ..config import load_settings, save_settings
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
    for key in ("writer", "extractor", "embedding"):
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


@router.get("/projects/{project_id}/sessions")
def get_sessions(project_id: str) -> list[dict[str, Any]]:
    _require_project(project_id)
    return db.list_sessions(project_id)


@router.post("/projects/{project_id}/sessions")
def post_session(project_id: str, req: CreateSessionRequest) -> dict[str, Any]:
    _require_project(project_id)
    return db.create_session(project_id, req.title, req.kind)


@router.get("/sessions/{session_id}/messages")
def get_messages(session_id: str) -> list[dict[str, Any]]:
    if not db.get_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return db.list_messages(session_id)


@router.delete("/sessions/{session_id}")
def remove_session(session_id: str) -> dict[str, bool]:
    db.delete_session(session_id)
    return {"ok": True}


# ---------------------------------------------------------------- 对话


class ChatRequest(BaseModel):
    session_id: str
    message: str
    style: str = ""
    mode: str = "main"


@router.post("/chat")
async def post_chat(req: ChatRequest) -> StreamingResponse:
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")
    return StreamingResponse(
        chat_stream(req.session_id, req.message, req.style, req.mode),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
