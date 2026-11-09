"""章节审稿：问题清单、状态与重跑。"""

from __future__ import annotations

from .common import (
    Any,
    HTTPException,
    Path,
    ReviewRequest,
    _require_project,
    review,
    router,
)


@router.get("/projects/{project_id}/reviews")
def get_reviews(project_id: str) -> list[dict[str, Any]]:
    project = _require_project(project_id)
    root = Path(project["path"])
    if not root.exists():
        raise HTTPException(status_code=404, detail="项目目录不存在")
    return review.list_reviews(root)


@router.get("/projects/{project_id}/review")
def get_review(project_id: str, chapter: str) -> dict[str, Any]:
    project = _require_project(project_id)
    root = Path(project["path"])
    if not root.exists():
        raise HTTPException(status_code=404, detail="项目目录不存在")
    try:
        return review.load_review(root, chapter) or {}
    except review.ReviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/review")
def post_review(project_id: str, req: ReviewRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    root = Path(project["path"])
    if not root.exists():
        raise HTTPException(status_code=404, detail="项目目录不存在")
    try:
        result = review.run_review(
            root,
            req.chapter,
            project_id=project_id,
            session_id=req.session_id,
            note=req.note,
        )
    except review.ReviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.to_dict()
