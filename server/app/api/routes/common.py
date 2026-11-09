from __future__ import annotations

import base64
import os
import shutil
import stat
import threading
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ... import db, memory, review
from ... import prompts as prompt_store
from ...agent import runs, steering, threads
from ...agent.checkpointer import drop_thread
from ...agent.compaction import compaction_plan
from ...agent.factory import resolve_expert
from ...agent.mcp_manager import MCP_ENABLED
from ...agent.mcp_manager import manager as mcp_manager
from ...agent.runner import approve_stream, chat_stream
from ...chapters import ChapterError
from ...chapters import create as create_chapter
from ...config import load_settings, resolve_model, save_settings
from ...context import assemble
from ...domains import list_domains
from ...experts import delete_expert, list_experts, save_expert
from ...export_book import ExportError
from ...export_book import export_txt as export_book_txt
from ...extract import accept_candidate, load_candidates, reject_candidate
from ...extract import jobs as extract_jobs
from ...extract import progress_summary as extract_progress
from ...extract import run as run_extract
from ...import_book import ImportError as BookImportError
from ...import_book import commit as import_commit
from ...import_book import preview as import_preview
from ...insight import MaterialError, collect_graph, collect_timeline, save_material
from ...kb.embedding import DEFAULT_LOCAL_MODEL, LOCAL_MODELS
from ...kb.embedding import probe as probe_embedding
from ...kb.lint import lint_project
from ...kb.repository import (
    KINDS,
    delete_entity,
    get_entity,
    list_entities,
    parse_note,
    save_entity,
)
from ...kb.search import KbIndex, load_kb_config, save_kb_config
from ...llm import normalize_window
from ...rewrite import RewriteError
from ...rewrite import rewrite as rewrite_text
from ...sandbox import check_command, check_path, check_url
from ...search_text import SearchError
from ...search_text import replace as text_replace
from ...search_text import search as text_search
from ...stats import sync_progress
from ...style_import import StyleImportError, import_style
from ...text import read_text, save_text
from ...usage import set_pricing as save_pricing
from ...usage import summary as usage_summary
from ...versioning import VersionError
from ...versioning import file_diff as version_diff
from ...versioning import files as version_files
from ...versioning import log as version_log
from ...versioning import read_file_at as version_read
from ...versioning import restore as version_restore
from ...workspace import (
    create_book,
    default_project_path,
    git_changes,
    git_commit,
    git_diff,
    git_status,
    git_status_map,
    read_book_meta,
    safe_join,
    snapshot_file,
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
    # MCP 服务器的 env 里常放 token / 密码，同样不能明文回显
    for server in data.get("mcp") or []:
        if not isinstance(server, dict):
            continue
        env = server.get("env")
        if isinstance(env, dict):
            server["env"] = {str(key): (MASKED_KEY if value else "") for key, value in env.items()}
    return data


# ---------------------------------------------------------------- 向量服务


class EmbeddingTestRequest(BaseModel):
    provider: str = "none"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    local_model: str = ""


# ---------------------------------------------------------------- 项目


class CreateProjectRequest(BaseModel):
    name: str
    title: str = ""
    author: str = ""
    path: str = ""
    words_per_chapter: int = 5000


def _purge_directory(target: Path, attempts: int = 4) -> None:
    """递归删目录；只读文件与短暂占用都要能扛住。

    两个坑叠在一起：
    - git 的松散对象与 pack 文件是 0444，Windows 上就是「只读」属性，
      `os.unlink` 会直接拒绝，而 `rmtree(ignore_errors=True)` 会**静默跳过**它们，
      于是目录看起来删了、其实还在。
    - 杀软扫描 / 索引服务也会短暂占用刚写完的文件，几十毫秒后释放。
    所以这里去掉只读位再删，并对整棵树退避重试。
    """

    def retry_once(func: Any, path: str, exc: BaseException) -> None:
        # 只读文件（比如 .git 里的对象）先去掉只读位再删一次
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            raise exc from None

    for attempt in range(attempts):
        try:
            shutil.rmtree(target, onexc=retry_once)
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.25 * (attempt + 1))


class OpenProjectRequest(BaseModel):
    path: str


class PricingRequest(BaseModel):
    pricing: dict[str, dict[str, float]] = Field(default_factory=dict)


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


def _with_running(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给会话列表带上「是否正在生成」，左侧栏据此显示转圈。"""
    live = runs.running_ids()
    return [{**item, "running": item["id"] in live} for item in items]


class PromptWrite(BaseModel):
    content: str
    project_id: str | None = None


def _prompt_project(project_id: str | None) -> Path | None:
    if not project_id:
        return None
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="空间不存在")
    return Path(project["path"])


# ---------------------------------------------------------------- 对话


class ChatRequest(BaseModel):
    session_id: str
    message: str
    mode: str = "main"
    expert_id: str | None = None
    references: list[dict[str, Any]] | None = None
    # 侧问：只读继承哪个主会话的最近上下文
    parent_session_id: str | None = None


def _run_response(
    session_id: str, factory: Any, *, conflict: str = "当前会话正在生成，请等这一轮结束或先停止。"
) -> StreamingResponse:
    """把一轮生成挂到后台任务上，响应体只是订阅。

    这样客户端断开（切会话、切空间）只会取消订阅，生成继续跑完并照常落库；
    切回来用 GET /sessions/{id}/run 拿快照继续看进展。
    """
    if runs.is_running(session_id):
        raise HTTPException(status_code=409, detail=conflict)
    state = runs.start(session_id, factory)
    return StreamingResponse(
        runs.tail(state),
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


class SandboxCheckRequest(BaseModel):
    kind: Literal["command", "url"]
    value: str


class SteerRequest(BaseModel):
    session_id: str
    message: str


class MemoryWrite(BaseModel):
    content: str
    project_id: str | None = None


class MemoryDelete(BaseModel):
    scope: str
    text: str
    project_id: str | None = None


# ---------------------------------------------------------------- 知识库


class EntityRequest(BaseModel):
    id: str
    meta: dict[str, Any] = Field(default_factory=dict)
    body: str = ""


class SearchRequest(BaseModel):
    query: str
    kinds: list[str] | None = None
    chapter_limit: int | None = None
    top_k: int = 8
    threshold: float = 0.0
    mode: str = "hybrid"
    alpha: float = 0.4


class MaterialRequest(BaseModel):
    text: str
    title: str = ""
    source: str = ""
    tags: list[str] = Field(default_factory=list)


_index_jobs: dict[str, dict[str, Any]] = {}


_index_lock = threading.Lock()


def _patch_job(project_id: str, **fields: Any) -> None:
    with _index_lock:
        current = dict(_index_jobs.get(project_id) or {})
        current.update(fields)
        _index_jobs[project_id] = current


def _run_index_job(project_id: str, root: Path, full: bool = False) -> None:
    while True:
        started_at = time.monotonic()

        def progress(stage: str, done: int, total: int, _start: float = started_at) -> None:
            # 重建可能跑几分钟（本地嵌入逐批编码），进度要能被前端轮询到。
            # started_at 用默认参数绑死当前轮次的值，避免闭包读到下一轮的循环变量。
            eta = 0
            if stage == "embed" and done > 0 and total > done:
                eta = int((time.monotonic() - _start) / done * (total - done))
            _patch_job(project_id, stage=stage, done=done, total=total, eta_seconds=eta)

        try:
            index = KbIndex(root, load_settings().embedding)
            result = index.rebuild(progress, full=full)
            payload: dict[str, Any] = {
                "running": False,
                "chunks": result["chunks"],
                "embedded": result["embedded"],
                # changed/skipped 让前端能说清「这次只重排了 3 个文件」
                "changed": result["changed"],
                "skipped": result["skipped"],
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
                "changed": 0,
                "skipped": 0,
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
            job.update(running=True, queued=False, stage="collect", done=0, total=0, error=None)
            _index_jobs[project_id] = job
            full = bool(job.get("full"))


def _start_index_job(project_id: str, root: Path, full: bool = False) -> dict[str, Any]:
    """登记任务并起线程：重建索引与导入后建库共用。

    已有任务在跑时不重复起线程，只打一个 queued 标记，让当前任务跑完再来一轮——
    否则「导入 → 立刻点重建」会因为 running 被忽略。
    """
    with _index_lock:
        current = _index_jobs.get(project_id)
        if current and current.get("running"):
            current["queued"] = True
            current["full"] = bool(current.get("full") or full)
            return dict(current)
        _index_jobs[project_id] = {
            "running": True,
            "queued": False,
            "full": full,
            "chunks": 0,
            "embedded": 0,
            "error": None,
            "stage": "collect",
            "done": 0,
            "total": 0,
        }
        job = dict(_index_jobs[project_id])
    threading.Thread(target=_run_index_job, args=(project_id, root, full), daemon=True).start()
    return job


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


# ---------------------------------------------------------------- 正文搜索 / 替换 / 改写


class TextSearchRequest(BaseModel):
    query: str
    scope: str = "manuscript"
    path: str | None = None
    regex: bool = False
    ignore_case: bool = False


class TextReplaceRequest(TextSearchRequest):
    replacement: str = ""
    dry_run: bool = True


class RewriteRequest(BaseModel):
    text: str
    action: str = "polish"
    tone: str = ""
    before: str = ""
    after: str = ""


# ---------------------------------------------------------------- 章节


class CreateChapterRequest(BaseModel):
    title: str = ""
    volume: int | None = None


# ---------------------------------------------------------------- 导出


class ExportTxtRequest(BaseModel):
    path: str = ""
    encoding: str = "utf-8"
    include_toc: bool = False


# ---------------------------------------------------------------- 逐章抽取


class ExtractRequest(BaseModel):
    limit: int = 0
    dry_run: bool = False


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


class KbConfigRequest(BaseModel):
    top_k: int = 8
    threshold: float = 0.0
    mode: str = "hybrid"
    alpha: float = 0.4
    chapter_limit: int | None = None


# ---------------------------------------------------------------- 专家


class ExpertRequest(BaseModel):
    id: str
    meta: dict[str, Any] = Field(default_factory=dict)
    body: str = ""


class ImportStyleRequest(BaseModel):
    path: str


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
    ".pdf",
    ".zip",
    ".gz",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".ico",
    ".mp3",
    ".mp4",
    ".wav",
    ".webm",
}


MAX_INLINE_IMAGE = 12 * 1024 * 1024


MAX_TEXT_INLINE = 2 * 1024 * 1024


class WriteFileRequest(BaseModel):
    path: str
    content: str
    # 打开文件时的 mtime；不一致说明已被 Agent 或其他操作改过
    expected_mtime: int | None = None


class FsCreateRequest(BaseModel):
    path: str
    kind: Literal["file", "dir"] = "file"


class FsRenameRequest(BaseModel):
    path: str
    new_path: str


def _guard_visible(root: Path, target: Path) -> None:
    if any(part in HIDDEN_PARTS for part in target.relative_to(root.resolve()).parts):
        raise HTTPException(status_code=400, detail="该路径不允许操作")


class CommitRequest(BaseModel):
    message: str = ""


class RestoreRequest(BaseModel):
    commit: str
    path: str


# ---------------------------------------------------------------- 工具


def _require_project(project_id: str) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _resolve_workspace_file(root: Path, path: str, operation: Literal["read", "write"]) -> Path:
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


def _sync_kb_index(project: Path, kind: str, entity_id: str) -> None:
    """单条卡片的增量索引。索引是派生物，失败不该让保存本身报错。"""
    try:
        KbIndex(project, load_settings().embedding).reindex_entity(
            kind, entity_id, build_baseline=False
        )
    except Exception:  # noqa: BLE001
        return


def _drop_kb_index(project: Path, kind: str, entity_id: str) -> None:
    try:
        KbIndex(project, load_settings().embedding).remove_entity(kind, entity_id)
    except Exception:  # noqa: BLE001
        return


def _drop_index_source(project: Path, relative: str) -> None:
    try:
        KbIndex(project, load_settings().embedding).remove_source(relative)
    except Exception:  # noqa: BLE001
        return


def _rename_index_source(project: Path, old: str, new: str) -> None:
    try:
        KbIndex(project, load_settings().embedding).rename_source(old, new)
    except Exception:  # noqa: BLE001
        return


def _kb_path_parts(relative: str) -> tuple[str, str] | None:
    """把 `kb/<kind>/<id>.md` 拆成 (kind, id)，其他路径返回 None。"""
    parts = Path(relative).parts
    if len(parts) != 3 or parts[0] != "kb" or not parts[2].endswith(".md"):
        return None
    if parts[1] not in KINDS:
        return None
    return parts[1], Path(parts[2]).stem


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


# ---------------------------------------------------------------- 审稿


class ReviewRequest(BaseModel):
    chapter: str
    note: str = ""
    session_id: str = ""


# ---------------------------------------------------------------- 拆解


class DeconstructRequest(BaseModel):
    source: str = ""
    group_size: int = 3
    max_groups: int = 3
    create_expert: bool = False


_deconstruct_jobs: dict[str, dict[str, Any]] = {}
_deconstruct_lock = threading.Lock()


_deconstruct_stop: set[str] = set()


def _deconstruct_worker(project_id: str, root: Path, source: Path, req: DeconstructRequest) -> None:
    job = _deconstruct_jobs[project_id]
    try:
        from ... import deconstruct

        result = deconstruct.run(
            root,
            source,
            group_size=req.group_size,
            max_groups=req.max_groups,
            create_expert=req.create_expert,
            project_id=project_id,
            progress=lambda data: job.update({"status": "running", "progress": data}),
            should_stop=lambda: project_id in _deconstruct_stop,
            allow_external=True,
        )
        job.update(
            {
                "status": "stopped" if project_id in _deconstruct_stop else "done",
                "result": result,
                "finished_at": time.time(),
            }
        )
    except Exception as exc:  # noqa: BLE001 - 任务失败要把原因带回前端
        job.update(
            {"status": "error", "error": f"{type(exc).__name__}: {exc}", "finished_at": time.time()}
        )
    finally:
        _deconstruct_stop.discard(project_id)
