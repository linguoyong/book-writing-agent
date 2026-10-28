from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from .. import db
from .approvals import build_requests
from .factory import build_agent, resolve_expert

MODE_BUILDER = {"expert_builder": "expert", "skill_builder": "skill"}


def _sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _as_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return ""


async def chat_stream(
    session_id: str,
    user_message: str,
    mode: str = "main",
    expert_id: str | None = None,
    references: list[dict[str, Any]] | None = None,
) -> AsyncIterator[str]:
    session = db.get_session(session_id)
    if not session:
        yield _sse("error", {"message": "会话不存在"})
        return
    project_row = db.get_project(session["project_id"])
    if not project_row:
        yield _sse("error", {"message": "项目不存在"})
        return

    project = Path(project_row["path"])
    if not project.exists():
        yield _sse("error", {"message": f"项目目录不存在：{project}"})
        return

    if db.pending_approval(session_id):
        yield _sse("error", {"message": "当前有待审批的写操作，请先通过或拒绝后再继续。"})
        return

    readonly = mode == "side" or session.get("kind") == "side"
    builder = MODE_BUILDER.get(mode, "")
    active_expert_id = expert_id or session.get("expert_id") or "general"
    expert = resolve_expert(project, active_expert_id)

    try:
        agent, bundle = build_agent(
            project,
            session=session,
            expert=expert,
            readonly=readonly,
            builder=builder,
            project_id=session["project_id"],
            references=references,
        )
    except Exception as exc:  # noqa: BLE001
        yield _sse("error", {"message": f"Agent 初始化失败：{type(exc).__name__}: {exc}"})
        return

    yield _sse(
        "context",
        {
            "items": [item.to_dict() for item in bundle.items],
            "fingerprint": bundle.fingerprint,
            "expert_id": bundle.expert_id,
            "domain_id": bundle.domain_id,
            "total_chars": bundle.total_chars,
        },
    )

    db.add_message(
        session_id,
        "user",
        user_message,
        meta={"references": references} if references else None,
    )
    if session["title"] == "新会话":
        db.update_session_title(session_id, user_message.strip()[:24] or "新会话")

    buffer: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    config = {"configurable": {"thread_id": session_id}}

    try:
        async for chunk in _run_events(
            agent,
            {"messages": [HumanMessage(content=user_message)]},
            config,
            buffer,
            tool_calls,
        ):
            yield chunk
    except Exception as exc:  # noqa: BLE001
        yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})
        return

    approval = await _approval_event(agent, config, session_id, project)
    _persist_assistant(session_id, buffer, tool_calls, awaiting=bool(approval))
    if approval:
        yield approval
    yield _sse(
        "done",
        {
            "chars": len("".join(buffer)),
            "fingerprint": bundle.fingerprint,
            "awaiting_approval": bool(approval),
        },
    )


async def approve_stream(
    session_id: str, decisions: list[dict[str, Any]]
) -> AsyncIterator[str]:
    session = db.get_session(session_id)
    if not session:
        yield _sse("error", {"message": "会话不存在"})
        return
    project_row = db.get_project(session["project_id"])
    if not project_row:
        yield _sse("error", {"message": "项目不存在"})
        return
    project = Path(project_row["path"])
    pending = db.pending_approval(session_id)
    if not pending:
        yield _sse("error", {"message": "没有待审批的操作"})
        return

    normalized = _normalize_decisions(decisions)
    expected = len(pending["payload"].get("requests") or [])
    if not normalized:
        yield _sse("error", {"message": "审批决定为空"})
        return
    if expected and len(normalized) != expected:
        yield _sse("error", {"message": f"审批数量不匹配：需要 {expected} 条决定"})
        return

    expert = resolve_expert(project, session.get("expert_id") or "general")
    try:
        agent, _ = build_agent(
            project,
            session=session,
            expert=expert,
            project_id=session["project_id"],
        )
    except Exception as exc:  # noqa: BLE001
        yield _sse("error", {"message": f"Agent 初始化失败：{type(exc).__name__}: {exc}"})
        return

    status = "rejected" if any(item["type"] == "reject" for item in normalized) else "approved"
    db.resolve_approvals(session_id, status)

    buffer: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    config = {"configurable": {"thread_id": session_id}}
    try:
        async for chunk in _run_events(
            agent,
            Command(resume={"decisions": normalized}),
            config,
            buffer,
            tool_calls,
        ):
            yield chunk
    except Exception as exc:  # noqa: BLE001
        yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})
        return

    approval = await _approval_event(agent, config, session_id, project)
    _persist_assistant(session_id, buffer, tool_calls, awaiting=bool(approval))
    if approval:
        yield approval
    yield _sse("done", {"chars": len("".join(buffer)), "awaiting_approval": bool(approval)})


async def _run_events(
    agent: Any,
    graph_input: Any,
    config: dict[str, Any],
    buffer: list[str],
    tool_calls: list[dict[str, Any]],
) -> AsyncIterator[str]:
    async for event in agent.astream_events(graph_input, config, version="v2"):
        kind = event.get("event")
        if kind == "on_chat_model_stream":
            text = _as_text(event.get("data", {}).get("chunk", {}).content)
            if text:
                buffer.append(text)
                yield _sse("token", {"text": text})
        elif kind == "on_tool_start":
            name = event.get("name", "tool")
            if name in {"write_todos"}:
                continue
            payload = {
                "name": name,
                "input": _truncate(event.get("data", {}).get("input", {})),
            }
            tool_calls.append({"name": name, "input": payload["input"]})
            yield _sse("tool_start", payload)
        elif kind == "on_tool_end":
            name = event.get("name", "tool")
            if name in {"write_todos"}:
                continue
            output = event.get("data", {}).get("output")
            content = getattr(output, "content", output)
            yield _sse("tool_end", {"name": name, "output": _truncate(content)})


async def _approval_event(
    agent: Any, config: dict[str, Any], session_id: str, project: Path
) -> str | None:
    try:
        snapshot = await agent.aget_state(config)
    except Exception:  # noqa: BLE001
        return None
    interrupts = getattr(snapshot, "interrupts", ()) or ()
    if not interrupts:
        return None

    interrupt = interrupts[0]
    value = interrupt.value if isinstance(interrupt.value, dict) else {}
    requests = build_requests(project, value)
    if not requests:
        return None
    record = db.add_approval(
        session_id, getattr(interrupt, "id", None), {"requests": requests}
    )
    return _sse(
        "approval",
        {
            "approval_id": record["id"],
            "interrupt_id": record.get("interrupt_id"),
            "requests": requests,
            "created_at": record["created_at"],
        },
    )


def _normalize_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in decisions or []:
        kind = str(item.get("type") or "")
        if kind not in {"approve", "reject"}:
            continue
        decision: dict[str, Any] = {"type": kind}
        if kind == "reject":
            decision["message"] = str(item.get("message") or "用户拒绝了这次写入")
        result.append(decision)
    return result


def _persist_assistant(
    session_id: str,
    buffer: list[str],
    tool_calls: list[dict[str, Any]],
    *,
    awaiting: bool,
) -> None:
    text = "".join(buffer)
    if not text.strip():
        return
    meta: dict[str, Any] = {}
    if tool_calls:
        meta["tool_calls"] = tool_calls
    if awaiting:
        meta["awaiting_approval"] = True
    db.add_message(session_id, "assistant", text, meta=meta or None)


def _truncate(value: Any, limit: int = 3000) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    return text[:limit]
