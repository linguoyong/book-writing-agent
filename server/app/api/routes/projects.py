"""项目 CRUD、概览、统计与项目级用量。"""

from __future__ import annotations

from .common import (
    KINDS,
    Any,
    CreateProjectRequest,
    HTTPException,
    KbIndex,
    OpenProjectRequest,
    Path,
    _purge_directory,
    _require_project,
    create_book,
    db,
    default_project_path,
    git_status,
    list_entities,
    load_settings,
    read_book_meta,
    router,
    sync_progress,
    usage_summary,
)


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
    path = create_book(req.name, req.title, req.author, req.path, req.words_per_chapter)
    existing = next((p for p in db.list_projects() if p["path"] == str(path)), None)
    if existing:
        return {**existing, "meta": read_book_meta(path)}
    project = db.create_project(req.name, str(path))
    return {**project, "meta": read_book_meta(path)}


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, purge: bool = False) -> dict[str, bool]:
    project = db.get_project(project_id)
    if not project:
        # 幂等：列表刷新慢一拍时重复点删除，不该报成「接口不存在」
        raise HTTPException(status_code=404, detail="空间不存在或已删除")
    if purge:
        target = Path(project["path"])
        if target.exists():
            try:
                _purge_directory(target)
            except OSError as exc:
                # 目录删不掉就整单回滚：记录保留，用户关掉占用后再点一次即可。
                # 之前是先删记录再删目录，失败后空间从列表消失、目录留在盘上，
                # 再点删除只会拿到 404。
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"目录删不掉：{target}（{type(exc).__name__}）。"
                        "可能是只读文件或程序正占用（杀毒扫描、后台建索引），稍后重试即可；"
                        "这次没有删除任何记录。"
                    ),
                ) from exc
    # 目录已清干净（或本来就不需要清）再删记录
    for session in db.list_sessions(project_id):
        db.delete_session(session["id"])
    db.delete_project(project_id)
    return {"ok": True}


@router.get("/projects/default-path")
def get_default_path(name: str = "未命名") -> dict[str, str]:
    """新建书稿的默认落点：~/.book-agent/books/<slug>。"""
    return {"path": str(default_project_path(name))}


@router.post("/projects/open")
def open_project(req: OpenProjectRequest) -> dict[str, Any]:
    target = Path(req.path).expanduser()
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=400, detail=f"目录不存在：{target}")
    path = target.resolve()
    existing = next((p for p in db.list_projects() if Path(p["path"]).resolve() == path), None)
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
        sorted((path / "manuscript").rglob("*.md")) if (path / "manuscript").exists() else []
    )
    index = KbIndex(path, load_settings().embedding)
    return {
        "book": read_book_meta(path),
        "kb_counts": counts,
        "chapter_count": len(chapters),
        "manuscript_count": len(manuscript),
        "index": index.stats(),
        "stats": sync_progress(path),
        "git_dirty": bool(git_status(path).strip()),
    }


@router.get("/projects/{project_id}/stats")
def project_stats(project_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    return sync_progress(Path(project["path"]))


@router.get("/projects/{project_id}/usage")
def project_usage(project_id: str, days: int = 14) -> dict[str, Any]:
    """按天/模型/会话聚合 token 用量，并按设置的单价折算成本。"""
    _require_project(project_id)
    return usage_summary(project_id, days)
