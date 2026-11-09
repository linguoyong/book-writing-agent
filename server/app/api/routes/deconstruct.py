"""作品拆解：结构分析、实体入库与专家生成。"""

from __future__ import annotations

from .common import (
    Any,
    DeconstructRequest,
    HTTPException,
    Path,
    _deconstruct_jobs,
    _deconstruct_stop,
    _deconstruct_worker,
    _import_source,
    _require_project,
    router,
    threading,
    time,
)


@router.post("/projects/{project_id}/deconstruct")
def start_deconstruct(project_id: str, req: DeconstructRequest) -> dict[str, Any]:

    project = _require_project(project_id)
    root = Path(project["path"])
    if not root.exists():
        raise HTTPException(status_code=404, detail="项目目录不存在")

    current = _deconstruct_jobs.get(project_id)
    if current and current.get("status") == "running":
        raise HTTPException(status_code=409, detail="这本书正在拆解，等它跑完或先停止")

    if req.source.strip():
        source = _import_source(req.source.strip())
    else:
        candidates = (
            sorted((root / "chapters").glob("*.md")) if (root / "chapters").exists() else []
        )
        if not candidates:
            raise HTTPException(status_code=400, detail="请指定源文件，或先把原书导入到 chapters/")
        source = candidates[0]

    _deconstruct_stop.discard(project_id)
    _deconstruct_jobs[project_id] = {
        "status": "running",
        "source": source.name,
        "started_at": time.time(),
        "progress": {},
    }
    threading.Thread(
        target=_deconstruct_worker,
        args=(project_id, root, source, req),
        daemon=True,
        name=f"deconstruct-{project_id}",
    ).start()
    return {"started": True, "source": source.name}


@router.get("/projects/{project_id}/deconstruct/status")
def deconstruct_status(project_id: str) -> dict[str, Any]:
    _require_project(project_id)
    job = _deconstruct_jobs.get(project_id)
    if not job:
        return {"status": "idle", "progress": {}}
    return job


@router.post("/projects/{project_id}/deconstruct/stop")
def stop_deconstruct(project_id: str) -> dict[str, bool]:
    _require_project(project_id)
    _deconstruct_stop.add(project_id)
    return {"stopping": True}
