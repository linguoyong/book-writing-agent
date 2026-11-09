"""导入导出、逐章抽取、选中改写、新建章节、专家与技能。"""

from __future__ import annotations

from .common import (
    Any,
    BookImportError,
    ChapterError,
    CreateChapterRequest,
    ExpertRequest,
    ExportError,
    ExportTxtRequest,
    ExtractRequest,
    HTTPException,
    ImportCommitRequest,
    ImportPreviewRequest,
    ImportStyleRequest,
    KbIndex,
    Path,
    RewriteError,
    RewriteRequest,
    SearchError,
    StyleImportError,
    TextReplaceRequest,
    TextSearchRequest,
    _import_source,
    _require_project,
    _start_index_job,
    accept_candidate,
    create_chapter,
    delete_expert,
    export_book_txt,
    extract_jobs,
    extract_progress,
    import_commit,
    import_preview,
    import_style,
    list_experts,
    load_candidates,
    load_settings,
    parse_note,
    read_text,
    reject_candidate,
    rewrite_text,
    router,
    run_extract,
    save_expert,
    sync_progress,
    text_replace,
    text_search,
    threading,
)


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


@router.post("/projects/{project_id}/text-search")
def search_text(project_id: str, req: TextSearchRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    try:
        return text_search(
            Path(project["path"]),
            req.query,
            scope=req.scope,
            path=req.path,
            regex=req.regex,
            ignore_case=req.ignore_case,
        )
    except SearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/text-replace")
def replace_text(project_id: str, req: TextReplaceRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    root = Path(project["path"])
    try:
        result = text_replace(
            root,
            req.query,
            req.replacement,
            scope=req.scope,
            path=req.path,
            regex=req.regex,
            ignore_case=req.ignore_case,
            dry_run=req.dry_run,
        )
    except SearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not req.dry_run and result["total"]:
        # 导入章节被改动后索引会旧，交给后台重建
        _start_index_job(project_id, root)
    return result


@router.post("/projects/{project_id}/rewrite")
def rewrite_selection(project_id: str, req: RewriteRequest) -> dict[str, Any]:
    _require_project(project_id)
    try:
        return rewrite_text(
            req.text,
            action=req.action,
            tone=req.tone,
            before=req.before,
            after=req.after,
            project_id=project_id,
        )
    except RewriteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapter")
def new_chapter(project_id: str, req: CreateChapterRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    try:
        result = create_chapter(Path(project["path"]), title=req.title, volume=req.volume)
    except ChapterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 新建后立刻同步进度，运行态与防剧透能马上看到新章
    sync_progress(Path(project["path"]))
    return result


@router.post("/projects/{project_id}/export/txt")
def export_txt(project_id: str, req: ExportTxtRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    try:
        return export_book_txt(
            Path(project["path"]),
            target=req.path,
            encoding=req.encoding,
            include_toc=req.include_toc,
        )
    except ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    result = run_extract(Path(project["path"]), limit=limit, dry_run=True, project_id=project_id)
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
                project_id=project_id,
            )
            extract_jobs.finish(project_id, error=None, stats=result)
            if result.get("chapters"):
                # 新建的卡与别名要进检索索引
                _start_index_job(project_id, root)
        except Exception as exc:  # noqa: BLE001
            extract_jobs.finish(project_id, error=f"{type(exc).__name__}: {exc}")

    threading.Thread(target=worker, daemon=True).start()
    return {"started": True, **extract_status(project_id)}


@router.get("/projects/{project_id}/extract/candidates")
def extract_candidates(project_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    items = load_candidates(Path(project["path"]))
    return {"total": len(items), "items": items}


@router.post("/projects/{project_id}/extract/candidates/{candidate_id}/accept")
def extract_accept(project_id: str, candidate_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    root = Path(project["path"])
    target = accept_candidate(root, candidate_id)
    if target is None:
        raise HTTPException(status_code=404, detail="这条候选不存在")

    def index_one() -> None:
        # 单独给这张卡建索引；首次会加载嵌入模型，别让它挡住「采纳」的响应
        try:
            KbIndex(root, load_settings().embedding).reindex_entity(
                target["kind"], str(target["name"])
            )
        except Exception:  # noqa: BLE001 - 索引失败不影响卡片已经写入
            pass

    threading.Thread(target=index_one, daemon=True).start()
    return {"ok": True, "accepted": target}


@router.post("/projects/{project_id}/extract/candidates/{candidate_id}/reject")
def extract_reject(project_id: str, candidate_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    return {"ok": reject_candidate(Path(project["path"]), candidate_id)}


@router.post("/projects/{project_id}/extract/stop")
def stop_extract(project_id: str) -> dict[str, Any]:
    _require_project(project_id)
    stopped = extract_jobs.stop(project_id)
    return {"stopped": stopped, **extract_status(project_id)}


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


@router.post("/projects/{project_id}/import-style")
def import_style_from_work(project_id: str, req: ImportStyleRequest) -> dict[str, Any]:
    """从已有作品提炼写作风格：生成风格专家 + 写作技能（不保留原文）。"""
    project = _require_project(project_id)
    source = Path(req.path).expanduser()
    try:
        return import_style(Path(project["path"]), source, project_id)
    except StyleImportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:  # 模型调用失败等
        raise HTTPException(status_code=502, detail=f"提炼失败：{error}") from error
