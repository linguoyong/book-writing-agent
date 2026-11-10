"""知识库卡片、混合检索、索引任务、关系图、时间线与一致性体检。"""

from __future__ import annotations

from .common import (
    KB_KIND_NAMES,
    KINDS,
    Any,
    EntityRequest,
    HTTPException,
    KbConfigRequest,
    KbIndex,
    MaterialError,
    MaterialRequest,
    Path,
    SearchRequest,
    _drop_kb_index,
    _index_jobs,
    _index_lock,
    _require_kind,
    _require_project,
    _start_index_job,
    _sync_kb_index,
    collect_graph,
    collect_timeline,
    delete_entity,
    get_entity,
    lint_project,
    list_entities,
    load_kb_config,
    load_settings,
    parse_note,
    read_text,
    router,
    save_entity,
    save_kb_config,
    save_material,
)


@router.get("/projects/{project_id}/lint")
def get_project_lint(project_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    path = Path(project["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="项目目录不存在")
    return lint_project(path)


# ---------------------------------------------------------------- 引用候选


@router.get("/projects/{project_id}/reference-candidates")
def reference_candidates(project_id: str, q: str = "", limit: int = 20) -> dict[str, Any]:
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


@router.get("/projects/{project_id}/kb/{kind}")
def get_entities(project_id: str, kind: str) -> list[dict[str, Any]]:
    project = _require_project(project_id)
    _require_kind(kind)
    return list_entities(Path(project["path"]), kind)


@router.post("/projects/{project_id}/kb/{kind}")
def post_entity(project_id: str, kind: str, req: EntityRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    _require_kind(kind)
    root = Path(project["path"])
    saved = save_entity(root, kind, req.id, req.meta, req.body)
    _sync_kb_index(root, kind, str(saved["id"]))
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
def put_entity(project_id: str, kind: str, entity_id: str, req: EntityRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    _require_kind(kind)
    root = Path(project["path"])
    saved = save_entity(root, kind, entity_id, req.meta, req.body)
    _sync_kb_index(root, kind, str(saved["id"]))
    return saved


@router.delete("/projects/{project_id}/kb/{kind}/{entity_id}")
def remove_entity(project_id: str, kind: str, entity_id: str) -> dict[str, bool]:
    project = _require_project(project_id)
    _require_kind(kind)
    root = Path(project["path"])
    deleted = delete_entity(root, kind, entity_id)
    if deleted:
        _drop_kb_index(root, kind, entity_id)
    return {"ok": deleted}


@router.post("/projects/{project_id}/materials")
def post_material(project_id: str, req: MaterialRequest) -> dict[str, Any]:
    """把一段摘录收进 kb/materials/，供后续写作引用。"""
    project = _require_project(project_id)
    try:
        saved = save_material(
            Path(project["path"]),
            req.text,
            title=req.title,
            source=req.source,
            tags=req.tags,
        )
    except MaterialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not saved.get("duplicate"):
        # 新卡片要进检索，正文一改索引就旧了
        _start_index_job(project_id, Path(project["path"]))
    return saved


@router.get("/projects/{project_id}/graph")
def project_graph(
    project_id: str, kinds: str = "", include_mentions: bool = True
) -> dict[str, Any]:
    project = _require_project(project_id)
    selected = [item.strip() for item in kinds.split(",") if item.strip()]
    return collect_graph(
        Path(project["path"]), kinds=selected or None, include_mentions=include_mentions
    )


@router.get("/projects/{project_id}/timeline")
def project_timeline(project_id: str, kinds: str = "") -> dict[str, Any]:
    project = _require_project(project_id)
    selected = [item.strip() for item in kinds.split(",") if item.strip()]
    return collect_timeline(Path(project["path"]), kinds=selected or None)


@router.post("/projects/{project_id}/search")
def search_kb(project_id: str, req: SearchRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    index = KbIndex(Path(project["path"]), load_settings().embedding)
    if not index.has_baseline():
        index.rebuild(embed=False)
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
def reindex_kb(project_id: str, full: bool = False) -> dict[str, Any]:
    """索引重建放到后台线程：百万字项目不会把请求挂住。

    默认增量（只重排改过的文件）；`?full=true` 才清空重来，
    留给「索引看着不对」的兜底，代价是整本重嵌。
    """
    project = _require_project(project_id)
    return _start_index_job(project_id, Path(project["path"]), full=full)


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


@router.get("/projects/{project_id}/kb-config")
def get_kb_config(project_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    return load_kb_config(Path(project["path"]))


@router.put("/projects/{project_id}/kb-config")
def put_kb_config(project_id: str, req: KbConfigRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    return save_kb_config(Path(project["path"]), req.model_dump())
