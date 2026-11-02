from __future__ import annotations

import base64
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import db, memory
from ..agent.checkpointer import drop_thread
from ..agent.compaction import compaction_plan
from ..agent.factory import resolve_expert
from ..agent.mcp_manager import manager as mcp_manager
from ..agent.runner import approve_stream, chat_stream
from ..agent import steering
from ..config import load_settings, resolve_model, save_settings
from ..context import assemble
from ..domains import list_domains
from ..experts import delete_expert, get_expert, list_experts, save_expert
from ..style_import import StyleImportError, import_style
from ..import_book import ImportError as BookImportError
from ..import_book import commit as import_commit
from ..extract import jobs as extract_jobs
from ..extract import progress_summary as extract_progress
from ..extract import run as run_extract
from ..import_book import preview as import_preview
from ..llm import normalize_window
from ..sandbox import check_command, check_path, check_url
from ..text import read_text
from ..kb.lint import lint_project
from ..kb.repository import (
    KINDS,
    delete_entity,
    get_entity,
    list_entities,
    parse_note,
    save_entity,
)
from ..kb.search import KbIndex, load_kb_config, save_kb_config
from ..kb.embedding import DEFAULT_LOCAL_MODEL, LOCAL_MODELS, probe as probe_embedding
from ..workspace import (
    create_book,
    default_project_path,
    git_changes,
    git_commit,
    git_diff,
    git_status,
    git_status_map,
    read_book_meta,
    safe_join,
    write_book_meta,
)

router = APIRouter()

HIDDEN_PARTS = {".git", ".index", "node_modules", "__pycache__"}
IGNORED_DIRS = HIDDEN_PARTS | {".venv", "dist", "out", ".workbuddy", ".screenshots"}
MAX_TREE_NODES = 3000

# GET /config 不返回明文密钥；PUT 时收到该占位符表示「保留原值」，
# 收到空串表示「清除」。前端密码框因此可以安全地显示 ***。
MASKED_KEY = "***"
SECRET_ROLES = ("writer", "extractor", "embedding")


def _mask_secrets(data: dict[str, Any]) -> dict[str, Any]:
    for role in SECRET_ROLES:
        section = data.get(role)
        if isinstance(section, dict):
            section["api_key"] = MASKED_KEY if section.get("api_key") else ""
    for item in data.get("models") or []:
        if isinstance(item, dict):
            item["api_key"] = MASKED_KEY if item.get("api_key") else ""
    return data


# ---------------------------------------------------------------- 配置


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/config")
def get_config() -> dict[str, Any]:
    return _mask_secrets(load_settings().model_dump())


@router.put("/config")
def put_config(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    merged = settings.model_dump()
    before_embedding = dict(merged.get("embedding") or {})
    for key in ("writer", "extractor", "embedding", "sandbox"):
        if key in payload and isinstance(payload[key], dict):
            patch = dict(payload[key])
            if patch.get("api_key") == MASKED_KEY:
                patch.pop("api_key", None)
            merged[key].update(patch)
    if isinstance(payload.get("mcp"), list):
        merged["mcp"] = payload["mcp"]
    if isinstance(payload.get("models"), list):
        previous = {
            str(item.get("id")): item
            for item in (merged.get("models") or [])
            if isinstance(item, dict)
        }
        models: list[dict[str, Any]] = []
        for item in payload["models"]:
            if not isinstance(item, dict):
                continue
            patch = dict(item)
            if patch.get("api_key") == MASKED_KEY:
                # 前端拿到的是 ***：按 id 回填原密钥，避免把占位符写进配置
                patch["api_key"] = previous.get(str(patch.get("id")), {}).get("api_key", "")
            models.append(patch)
        merged["models"] = models
    if isinstance(payload.get("active_model_id"), str):
        merged["active_model_id"] = payload["active_model_id"]
    for role in ("writer", "extractor"):
        if merged.get(role, {}).get("context_window"):
            merged[role]["context_window"] = normalize_window(merged[role]["context_window"])
    save_settings(type(settings).model_validate(merged))
    saved = load_settings()
    after_embedding = saved.embedding
    changed = any(
        before_embedding.get(key) != getattr(after_embedding, key)
        for key in ("provider", "local_model", "model", "base_url")
    )
    result = _mask_secrets(saved.model_dump())
    # 前端的 AppConfig 不认识这个字段也没关系：只是用来提示「需要重建索引」
    result["embedding_changed"] = changed
    return result


# ---------------------------------------------------------------- 向量服务


class EmbeddingTestRequest(BaseModel):
    provider: str = "none"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    local_model: str = ""


@router.get("/embeddings/options")
def embedding_options() -> dict[str, Any]:
    return {
        "default": DEFAULT_LOCAL_MODEL,
        "local": [{"id": key, **value} for key, value in LOCAL_MODELS.items()],
    }


@router.post("/embeddings/test")
def test_embedding(req: EmbeddingTestRequest) -> dict[str, Any]:
    """真跑一次编码：本地模型首次会下载/加载，可能要几十秒。"""
    cfg = load_settings().embedding.model_copy(deep=True)
    cfg.provider = req.provider or cfg.provider
    if req.base_url:
        cfg.base_url = req.base_url
    if req.model:
        cfg.model = req.model
    if req.local_model:
        cfg.local_model = req.local_model
    if req.api_key and req.api_key != MASKED_KEY:
        cfg.api_key = req.api_key
    return probe_embedding(cfg)


# ---------------------------------------------------------------- 项目


class CreateProjectRequest(BaseModel):
    name: str
    title: str = ""
    author: str = ""
    path: str = ""
    words_per_chapter: int = 5000


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
    path = create_book(
        req.name, req.title, req.author, req.path, req.words_per_chapter
    )
    existing = next((p for p in db.list_projects() if p["path"] == str(path)), None)
    if existing:
        return {**existing, "meta": read_book_meta(path)}
    project = db.create_project(req.name, str(path))
    return {**project, "meta": read_book_meta(path)}


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, purge: bool = False) -> dict[str, bool]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="空间不存在")
    # 先删会话（连带消息与审批），再删空间记录
    for session in db.list_sessions(project_id):
        db.delete_session(session["id"])
    db.delete_project(project_id)
    if purge:
        target = Path(project["path"])
        shutil.rmtree(target, ignore_errors=True)
        if target.exists():
            raise HTTPException(
                status_code=500,
                detail="目录删除失败（可能有文件被占用），空间与会话记录已删除",
            )
    return {"ok": True}


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
    model_id: str | None = None


class SessionPatch(BaseModel):
    title: str | None = None
    expert_id: str | None = None
    domain: str | None = None
    permission_mode: str | None = None
    model_id: str | None = None
    archived: bool | None = None


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
        req.model_id,
    )


@router.get("/sessions")
def list_all_sessions() -> list[dict[str, Any]]:
    return db.list_all_sessions()


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
    settings = load_settings()
    profile = resolve_model(settings, session.get("model_id"))
    payload = bundle.to_dict()
    payload["model"] = {
        "id": profile.id,
        "name": profile.name or profile.model,
        "model": profile.model,
        "context_window": profile.context_window,
        "max_output_tokens": profile.max_output_tokens,
    }
    payload["compaction"] = compaction_plan(profile.context_window)
    return payload


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
    # 侧问：只读继承哪个主会话的最近上下文
    parent_session_id: str | None = None


@router.post("/chat")
async def post_chat(req: ChatRequest) -> StreamingResponse:
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")
    return StreamingResponse(
        chat_stream(
            req.session_id,
            req.message,
            req.mode,
            req.expert_id,
            req.references,
            req.parent_session_id,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class Decision(BaseModel):
    type: str
    message: str | None = None
    # type=edit 时携带人工修改后的工具名与参数
    edited_action: dict[str, Any] | None = None


class ApproveRequest(BaseModel):
    session_id: str
    decisions: list[Decision]


@router.post("/sessions/{session_id}/regenerate")
def regenerate_session(session_id: str) -> StreamingResponse:
    """删掉最后一轮回答，换一个 thread 重放历史消息后重新生成。"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if db.pending_approval(session_id):
        raise HTTPException(status_code=400, detail="当前有待审批的写操作，处理后再重新生成")

    messages = db.list_messages(session_id)
    last_user_index = -1
    for index in range(len(messages) - 1, -1, -1):
        if messages[index]["role"] == "user":
            last_user_index = index
            break
    if last_user_index < 0:
        raise HTTPException(status_code=400, detail="没有可重新生成的消息")

    for item in messages[last_user_index + 1 :]:
        db.delete_message(int(item["id"]))

    # 换 thread：旧 checkpoint 里还有上一轮回答，继续用会让模型重复原答案
    db.update_session(
        session_id, thread_id=f"{session_id}-r{int(time.time() * 1000)}"
    )
    history = db.list_messages(session_id)
    mode = "side" if session.get("kind") == "side" else "main"
    return StreamingResponse(
        chat_stream(
            session_id,
            str(messages[last_user_index]["content"]),
            mode,
            session.get("expert_id"),
            None,
            None,
            history,
            False,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/approve")
async def post_approve(req: ApproveRequest) -> StreamingResponse:
    decisions = [item.model_dump(exclude_none=True) for item in req.decisions]
    return StreamingResponse(
        approve_stream(req.session_id, decisions),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/mcp/status")
async def mcp_status() -> dict[str, Any]:
    status = await mcp_manager.refresh()
    return {"servers": status}


@router.post("/mcp/reload")
async def mcp_reload() -> dict[str, Any]:
    status = await mcp_manager.refresh(force=True)
    return {"servers": status}


class SandboxCheckRequest(BaseModel):
    kind: Literal["command", "url"]
    value: str


@router.post("/sandbox/check")
def sandbox_check(req: SandboxCheckRequest) -> dict[str, Any]:
    settings = load_settings()
    fn = check_command if req.kind == "command" else check_url
    return {"result": fn(settings.sandbox, req.value)}


@router.get("/projects/{project_id}/lint")
def get_project_lint(project_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    path = Path(project["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="项目目录不存在")
    return lint_project(path)


@router.get("/projects/{project_id}/approvals")
def get_project_approvals(
    project_id: str, status: str = "all", limit: int = 50
) -> list[dict[str, Any]]:
    _require_project(project_id)
    return db.list_approvals(project_id, status=status, limit=limit)


@router.get("/sessions/{session_id}/pending")
def get_pending(session_id: str) -> dict[str, Any]:
    if not db.get_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"approval": db.pending_bundle(session_id)}


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
            meta, _ = parse_note(read_text(file))
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
    alpha: float = 0.4


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


_index_jobs: dict[str, dict[str, Any]] = {}
_index_lock = threading.Lock()


def _patch_job(project_id: str, **fields: Any) -> None:
    with _index_lock:
        current = dict(_index_jobs.get(project_id) or {})
        current.update(fields)
        _index_jobs[project_id] = current


def _run_index_job(project_id: str, root: Path) -> None:
    while True:
        started_at = time.monotonic()

        def progress(stage: str, done: int, total: int) -> None:
            # 重建可能跑几分钟（本地嵌入逐批编码），进度要能被前端轮询到
            eta = 0
            if stage == "embed" and done > 0 and total > done:
                eta = int((time.monotonic() - started_at) / done * (total - done))
            _patch_job(project_id, stage=stage, done=done, total=total, eta_seconds=eta)

        try:
            index = KbIndex(root, load_settings().embedding)
            result = index.rebuild(progress)
            payload: dict[str, Any] = {
                "running": False,
                "chunks": result["chunks"],
                "embedded": result["embedded"],
                "error": index.last_vector_error or None,
                "stage": "done",
                "done": result["embedded"],
                "total": result["chunks"],
            }
        except Exception as exc:  # noqa: BLE001
            payload = {
                "running": False,
                "chunks": 0,
                "embedded": 0,
                "error": f"{type(exc).__name__}: {exc}",
                "stage": "error",
                "done": 0,
                "total": 0,
            }
        _patch_job(project_id, **payload)

        # 跑的过程中又被要求重建（比如导入刚建完就点了「重建索引」）：
        # 不能吞掉这次请求，接着再跑一轮
        with _index_lock:
            job = dict(_index_jobs.get(project_id) or {})
            if not job.get("queued"):
                break
            job.update(
                running=True, queued=False, stage="collect", done=0, total=0, error=None
            )
            _index_jobs[project_id] = job


def _start_index_job(project_id: str, root: Path) -> dict[str, Any]:
    """登记任务并起线程：重建索引与导入后建库共用。

    已有任务在跑时不重复起线程，只打一个 queued 标记，让当前任务跑完再来一轮——
    否则「导入 → 立刻点重建」会因为 running 被忽略。
    """
    with _index_lock:
        current = _index_jobs.get(project_id)
        if current and current.get("running"):
            current["queued"] = True
            return dict(current)
        _index_jobs[project_id] = {
            "running": True,
            "queued": False,
            "chunks": 0,
            "embedded": 0,
            "error": None,
            "stage": "collect",
            "done": 0,
            "total": 0,
        }
        job = dict(_index_jobs[project_id])
    threading.Thread(
        target=_run_index_job, args=(project_id, root), daemon=True
    ).start()
    return job


@router.post("/projects/{project_id}/reindex")
def reindex_kb(project_id: str) -> dict[str, Any]:
    """索引重建放到后台线程：百万字项目不会把请求挂住。"""
    project = _require_project(project_id)
    return _start_index_job(project_id, Path(project["path"]))


@router.get("/projects/{project_id}/index/status")
def index_status(project_id: str) -> dict[str, Any]:
    with _index_lock:
        return _index_jobs.get(project_id) or {
            "running": False,
            "chunks": None,
            "embedded": None,
            "error": None,
            "stage": "idle",
            "done": 0,
            "total": 0,
        }


# ---------------------------------------------------------------- 整本书导入


class ImportPreviewRequest(BaseModel):
    path: str
    pattern: str = ""


class ImportCommitRequest(BaseModel):
    path: str
    pattern: str = ""
    excluded: list[int] = Field(default_factory=list)
    titles: dict[str, str] = Field(default_factory=dict)


def _import_source(path: str) -> Path:
    source = Path(path).expanduser()
    if not source.is_absolute():
        raise HTTPException(status_code=400, detail="请传绝对路径")
    return source


@router.post("/projects/{project_id}/import/preview")
def preview_import(project_id: str, req: ImportPreviewRequest) -> dict[str, Any]:
    _require_project(project_id)
    try:
        return import_preview(_import_source(req.path), req.pattern)
    except BookImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/import")
def commit_import(project_id: str, req: ImportCommitRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    root = Path(project["path"])
    try:
        result = import_commit(
            root,
            _import_source(req.path),
            pattern=req.pattern,
            excluded=req.excluded,
            titles=req.titles,
        )
    except BookImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 导入完立刻在后台建索引，几百万字也不用等
    _start_index_job(project_id, root)
    return result


# ---------------------------------------------------------------- 逐章抽取


class ExtractRequest(BaseModel):
    limit: int = 0
    dry_run: bool = False


@router.get("/projects/{project_id}/extract/status")
def extract_status(project_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    summary = extract_progress(Path(project["path"]))
    return {
        "running": extract_jobs.status(project_id).get("running", False),
        "run": extract_jobs.status(project_id),
        "state": summary,
    }


@router.post("/projects/{project_id}/extract/preview")
def extract_preview(project_id: str, req: ExtractRequest) -> dict[str, Any]:
    """试抽取：同步跑几章，只统计不落盘，用来验收字段质量。"""
    project = _require_project(project_id)
    limit = max(1, min(req.limit or 5, 10))
    result = run_extract(
        Path(project["path"]), limit=limit, dry_run=True
    )
    summary = extract_progress(Path(project["path"]))
    return {"preview": result, "state": summary}


@router.post("/projects/{project_id}/extract")
def start_extract(project_id: str, req: ExtractRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    root = Path(project["path"])
    if not extract_jobs.start(project_id):
        return {"started": False, **extract_status(project_id)}

    def worker() -> None:
        try:
            result = run_extract(
                root,
                limit=max(0, req.limit),
                dry_run=False,
                progress=lambda payload: extract_jobs.update(
                    project_id,
                    done=payload["done"],
                    total=payload["total"],
                    chapter=payload["chapter"],
                    title=payload["title"],
                    stats=payload["stats"],
                ),
                should_stop=lambda: extract_jobs.stopped(project_id),
            )
            extract_jobs.finish(project_id, error=None, stats=result)
            if result.get("chapters"):
                # 新建的卡与别名要进检索索引
                _start_index_job(project_id, root)
        except Exception as exc:  # noqa: BLE001
            extract_jobs.finish(project_id, error=f"{type(exc).__name__}: {exc}")

    threading.Thread(target=worker, daemon=True).start()
    return {"started": True, **extract_status(project_id)}


@router.post("/projects/{project_id}/extract/stop")
def stop_extract(project_id: str) -> dict[str, Any]:
    _require_project(project_id)
    stopped = extract_jobs.stop(project_id)
    return {"stopped": stopped, **extract_status(project_id)}


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
    # 不在这里触发重建：开了本地向量后首次建库要跑模型，页面加载会被挂住
    chunk_stats = index.stats_by_kind() if index.has_baseline() else {}
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
    if not index.has_baseline():
        # 打开切片页只补文本索引，向量交给「重建索引」的后台任务
        index.rebuild(embed=False)
    return index.list_chunks(kind, limit, offset, q)


class KbConfigRequest(BaseModel):
    top_k: int = 8
    threshold: float = 0.0
    mode: str = "hybrid"
    alpha: float = 0.4
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
        meta, body = parse_note(read_text(file))
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


class ImportStyleRequest(BaseModel):
    path: str


@router.post("/projects/{project_id}/import-style")
def import_style_from_work(project_id: str, req: ImportStyleRequest) -> dict[str, Any]:
    """从已有作品提炼写作风格：生成风格专家 + 写作技能（不保留原文）。"""
    project = _require_project(project_id)
    source = Path(req.path).expanduser()
    try:
        return import_style(Path(project["path"]), source)
    except StyleImportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:  # 模型调用失败等
        raise HTTPException(status_code=502, detail=f"提炼失败：{error}") from error


# ---------------------------------------------------------------- 文件


@router.get("/projects/{project_id}/tree")
def get_tree(project_id: str) -> list[dict[str, Any]]:
    """整个工作区的文件树（排除 .git/.index 等），带 git 状态标记。"""
    project = _require_project(project_id)
    root = Path(project["path"])
    if not root.exists():
        raise HTTPException(status_code=404, detail="项目目录不存在")
    git_map = git_status_map(root) if (root / ".git").exists() else {}
    budget = [MAX_TREE_NODES]
    return [_tree_node(root, root, git_map, budget)]


IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}
BINARY_EXT = {
    ".pdf", ".zip", ".gz", ".7z", ".rar", ".exe", ".dll", ".so", ".dylib",
    ".woff", ".woff2", ".ttf", ".otf", ".ico", ".mp3", ".mp4", ".wav", ".webm",
}
MAX_INLINE_IMAGE = 12 * 1024 * 1024
MAX_TEXT_INLINE = 2 * 1024 * 1024


@router.get("/projects/{project_id}/file")
def read_file(project_id: str, path: str, head: int | None = None) -> dict[str, Any]:
    project = _require_project(project_id)
    root = Path(project["path"])
    target = _resolve_workspace_file(root, path, "read")
    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="文件不存在")

    suffix = target.suffix.lower()
    stat = target.stat()
    size = stat.st_size
    mtime = int(stat.st_mtime * 1000)
    if suffix in IMAGE_MIME and size <= MAX_INLINE_IMAGE:
        encoded = base64.b64encode(target.read_bytes()).decode("ascii")
        return {
            "path": path,
            "kind": "image",
            "mime": IMAGE_MIME[suffix],
            "data_url": f"data:{IMAGE_MIME[suffix]};base64,{encoded}",
            "size": size,
            "mtime": mtime,
        }
    if suffix in BINARY_EXT or suffix in IMAGE_MIME:
        return {"path": path, "kind": "binary", "size": size, "mtime": mtime}
    if head is None and size > MAX_TEXT_INLINE:
        # 百万字级别的稿件整份塞进编辑器会卡死，先让用户选择只读分段预览
        return {"path": path, "kind": "large", "size": size, "mtime": mtime}
    content = read_text(target)
    truncated = False
    if head is not None and len(content) > head:
        content = content[:head]
        truncated = True
    return {
        "path": path,
        "kind": "text",
        "content": content,
        "size": size,
        "mtime": mtime,
        "truncated": truncated,
    }


class WriteFileRequest(BaseModel):
    path: str
    content: str
    # 打开文件时的 mtime；不一致说明已被 Agent 或其他操作改过
    expected_mtime: int | None = None


@router.put("/projects/{project_id}/file")
def write_file(project_id: str, req: WriteFileRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    root = Path(project["path"])
    target = _resolve_workspace_file(root, req.path, "write")
    if any(part in HIDDEN_PARTS for part in target.relative_to(root.resolve()).parts):
        raise HTTPException(status_code=400, detail="该路径不允许写入")
    if req.expected_mtime is not None and target.exists():
        current = int(target.stat().st_mtime * 1000)
        if abs(current - req.expected_mtime) > 2:
            raise HTTPException(
                status_code=409, detail="文件已被其他操作修改，请重新加载后再保存"
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(req.content, encoding="utf-8")
    return {"ok": True, "mtime": int(target.stat().st_mtime * 1000)}


class FsCreateRequest(BaseModel):
    path: str
    kind: Literal["file", "dir"] = "file"


class FsRenameRequest(BaseModel):
    path: str
    new_path: str


def _guard_visible(root: Path, target: Path) -> None:
    if any(part in HIDDEN_PARTS for part in target.relative_to(root.resolve()).parts):
        raise HTTPException(status_code=400, detail="该路径不允许操作")


@router.post("/projects/{project_id}/fs/create")
def fs_create(project_id: str, req: FsCreateRequest) -> dict[str, bool]:
    project = _require_project(project_id)
    root = Path(project["path"])
    target = _resolve_workspace_file(root, req.path, "write")
    _guard_visible(root, target)
    if target.exists():
        raise HTTPException(status_code=409, detail="目标已存在")
    if req.kind == "dir":
        target.mkdir(parents=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    return {"ok": True}


@router.post("/projects/{project_id}/fs/rename")
def fs_rename(project_id: str, req: FsRenameRequest) -> dict[str, bool]:
    project = _require_project(project_id)
    root = Path(project["path"])
    source = _resolve_workspace_file(root, req.path, "write")
    target = _resolve_workspace_file(root, req.new_path, "write")
    _guard_visible(root, source)
    _guard_visible(root, target)
    if not source.exists():
        raise HTTPException(status_code=404, detail="源文件不存在")
    if target.exists():
        raise HTTPException(status_code=409, detail="目标已存在")
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return {"ok": True}


@router.delete("/projects/{project_id}/fs")
def fs_delete(project_id: str, path: str) -> dict[str, bool]:
    project = _require_project(project_id)
    root = Path(project["path"])
    target = _resolve_workspace_file(root, path, "write")
    if target == root.resolve():
        raise HTTPException(status_code=400, detail="不能删除工作区根目录")
    _guard_visible(root, target)
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
    else:
        raise HTTPException(status_code=404, detail="文件不存在")
    return {"ok": True}


# ---------------------------------------------------------------- git


@router.get("/projects/{project_id}/git/status")
def get_git_status(project_id: str) -> dict[str, str]:
    project = _require_project(project_id)
    return {"status": git_status(Path(project["path"]))}


@router.get("/projects/{project_id}/git/diff")
def get_git_diff(project_id: str, path: str | None = None) -> dict[str, str]:
    project = _require_project(project_id)
    return {"diff": git_diff(Path(project["path"]), path)}


@router.get("/projects/{project_id}/git/changes")
def get_git_changes(project_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    return {"items": git_changes(Path(project["path"]))}


class CommitRequest(BaseModel):
    message: str = ""


@router.post("/projects/{project_id}/git/commit")
def post_git_commit(project_id: str, req: CommitRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    message = req.message.strip() or "保存当前修改"
    ok, output = git_commit(Path(project["path"]), message)
    if not ok:
        raise HTTPException(status_code=400, detail=output)
    return {"ok": True, "message": output}


# ---------------------------------------------------------------- 工具


def _require_project(project_id: str) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _resolve_workspace_file(
    root: Path, path: str, operation: Literal["read", "write"]
) -> Path:
    """REST 文件读写与 Agent 工具共用同一套边界：先防越界，再过路径规则。

    这里按「真实解析后的相对路径」匹配规则，`manuscript/../.env` 这类写法
    也会被归一化成 `.env` 后命中 deny。
    """
    try:
        target = safe_join(root, path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="路径越界") from exc
    relative = target.relative_to(root.resolve()).as_posix()
    if check_path(load_settings().sandbox, relative, operation) == "deny":
        label = "读取" if operation == "read" else "写入"
        raise HTTPException(status_code=403, detail=f"路径规则禁止{label}：{relative}")
    return target


def _require_kind(kind: str) -> None:
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"未知知识库类型: {kind}")


def _tree_node(
    root: Path, path: Path, git_map: dict[str, str], budget: list[int]
) -> dict[str, Any]:
    budget[0] -= 1
    relative = "" if path == root else str(path.relative_to(root)).replace("\\", "/")
    node: dict[str, Any] = {
        "name": path.name or str(path),
        "path": relative or ".",
        "type": "dir" if path.is_dir() else "file",
    }
    if path.is_dir():
        children: list[dict[str, Any]] = []
        if budget[0] > 0:
            for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name)):
                if child.name in IGNORED_DIRS:
                    continue
                if budget[0] <= 0:
                    break
                children.append(_tree_node(root, child, git_map, budget))
        node["children"] = children
        # 目录本身不跟踪状态，但内部有改动时给一个聚合标记，前端画小圆点
        node["git"] = "modified" if any(child.get("git") for child in children) else ""
    else:
        node["git"] = git_map.get(relative, "")
    return node
