"""git 状态、提交、历史、单文件 diff 与回滚。"""

from __future__ import annotations

from .common import (
    Any,
    CommitRequest,
    HTTPException,
    Path,
    RestoreRequest,
    VersionError,
    _require_project,
    _start_index_job,
    git_changes,
    git_commit,
    git_diff,
    git_status,
    router,
    sync_progress,
    version_diff,
    version_files,
    version_log,
    version_read,
    version_restore,
)

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


@router.get("/projects/{project_id}/git/log")
def git_log(project_id: str, limit: int = 40) -> dict[str, Any]:
    project = _require_project(project_id)
    return {"items": version_log(Path(project["path"]), limit)}


@router.get("/projects/{project_id}/git/files")
def git_commit_files(project_id: str, commit: str) -> dict[str, Any]:
    project = _require_project(project_id)
    try:
        return {"items": version_files(Path(project["path"]), commit)}
    except VersionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/git/file-diff")
def git_file_diff(project_id: str, commit: str, path: str) -> dict[str, Any]:
    project = _require_project(project_id)
    try:
        return version_diff(Path(project["path"]), commit, path)
    except VersionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/git/file")
def git_file_at(project_id: str, commit: str, path: str) -> dict[str, Any]:
    project = _require_project(project_id)
    try:
        return version_read(Path(project["path"]), commit, path)
    except VersionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/git/restore")
def git_restore(project_id: str, req: RestoreRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    root = Path(project["path"])
    try:
        result = version_restore(root, req.commit, req.path)
    except VersionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 恢复成功后立刻同步统计与索引
    sync_progress(root)
    _start_index_job(project_id, root)
    return result


@router.post("/projects/{project_id}/git/commit")
def post_git_commit(project_id: str, req: CommitRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    message = req.message.strip() or "保存当前修改"
    ok, output = git_commit(Path(project["path"]), message)
    if not ok:
        raise HTTPException(status_code=400, detail=output)
    return {"ok": True, "message": output}
