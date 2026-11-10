"""会话、对话流、审批、引导、提示词层与记忆。"""

from __future__ import annotations

from .common import (
    Any,
    ApproveRequest,
    ChatRequest,
    CreateSessionRequest,
    HTTPException,
    MemoryDelete,
    MemoryWrite,
    Path,
    PromptWrite,
    SessionPatch,
    SteerRequest,
    StreamingResponse,
    _prompt_project,
    _require_project,
    _run_response,
    _with_running,
    approve_stream,
    assemble,
    chat_stream,
    compaction_plan,
    db,
    drop_thread,
    load_settings,
    memory,
    prompt_store,
    resolve_expert,
    resolve_model,
    router,
    runs,
    steering,
    threads,
)


@router.get("/projects/{project_id}/sessions")
def get_sessions(project_id: str) -> list[dict[str, Any]]:
    _require_project(project_id)
    return _with_running(db.list_sessions(project_id))


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


@router.get("/prompts")
def list_prompts(project_id: str | None = None) -> dict[str, Any]:
    """系统提示词各层：体积、预算、是否改过。"""
    return {"items": prompt_store.describe(_prompt_project(project_id))}


@router.get("/prompts/{layer}")
def get_prompt(layer: str, project_id: str | None = None) -> dict[str, Any]:
    project = _prompt_project(project_id)
    try:
        return {
            "layer": layer,
            "content": prompt_store.read_layer(layer, project),
            "default": prompt_store.default_content(layer),
            "path": str(prompt_store.layer_path(layer, project)),
            "overridable": prompt_store.LAYERS[layer][2],
        }
    except prompt_store.PromptError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/prompts/{layer}")
def put_prompt(layer: str, req: PromptWrite) -> dict[str, Any]:
    project = _prompt_project(req.project_id)
    try:
        file = prompt_store.write_layer(layer, req.content, project)
    except prompt_store.PromptError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "path": str(file), "chars": len(req.content)}


@router.post("/prompts/{layer}/reset")
def reset_prompt(layer: str, project_id: str | None = None) -> dict[str, bool]:
    project = _prompt_project(project_id)
    try:
        prompt_store.reset_layer(layer, project)
    except prompt_store.PromptError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/sessions")
def list_all_sessions() -> list[dict[str, Any]]:
    return _with_running(db.list_all_sessions())


@router.post("/sessions/{session_id}/run/stop")
def stop_session_run(session_id: str) -> dict[str, bool]:
    """停止正在跑的这一轮（切走再回来时也能停）。"""
    return {"ok": runs.cancel(session_id)}


@router.get("/sessions/{session_id}/run")
def session_run(session_id: str) -> dict[str, Any]:
    """切回会话时取这一轮的进展：是否在跑、已生成的文本与工具步骤。"""
    state = runs.get_run(session_id)
    if state is None:
        return {
            "session_id": session_id,
            "running": False,
            "items": [],
            "text": "",
            "error": "",
            "elapsed_ms": 0,
        }
    return state.snapshot()


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
    if runs.is_running(session_id) or steering.is_running(session_id):
        raise HTTPException(status_code=409, detail="会话正在生成，请先停止再删除")
    db.delete_session(session_id)
    await drop_thread(session_id)
    return {"ok": True}


@router.post("/chat")
async def post_chat(req: ChatRequest) -> StreamingResponse:
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")
    return _run_response(
        req.session_id,
        lambda: chat_stream(
            req.session_id,
            req.message,
            req.mode,
            req.expert_id,
            req.references,
            req.parent_session_id,
        ),
    )


@router.post("/sessions/{session_id}/regenerate")
async def regenerate_session(session_id: str) -> StreamingResponse:
    """删掉最后一轮回答，换一个 thread 重放历史消息后重新生成。"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if db.pending_approval(session_id):
        raise HTTPException(status_code=400, detail="当前有待审批的写操作，处理后再重新生成")
    # 先拦一道：重新生成会先删掉上一轮回答，等流开始才拒绝就来不及了。
    # runs 里还有任务时同样不能动，否则会把正在用的历史删掉。
    if steering.is_running(session_id) or runs.is_running(session_id):
        raise HTTPException(status_code=409, detail="当前会话还在生成，等这一轮结束或先停止再重试")

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
    db.update_session(session_id, thread_id=threads.fork_thread(session_id))
    history = db.list_messages(session_id)
    mode = "side" if session.get("kind") == "side" else "main"
    return _run_response(
        session_id,
        lambda: chat_stream(
            session_id,
            str(messages[last_user_index]["content"]),
            mode,
            session.get("expert_id"),
            None,
            None,
            history,
            False,
        ),
    )


@router.post("/chat/approve")
async def post_approve(req: ApproveRequest) -> StreamingResponse:
    decisions = [item.model_dump(exclude_none=True) for item in req.decisions]
    return _run_response(req.session_id, lambda: approve_stream(req.session_id, decisions))


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
        return memory.distill_session(session_id, project, session["project_id"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"沉淀失败：{exc}") from exc
