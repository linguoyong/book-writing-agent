from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage

from .. import db
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
        )
    except Exception as exc:  # noqa: BLE001
        yield _sse("error", {"message": f"Agent 初始化失败：{type(exc).__name__}: {exc}"})
        return

    # 先把「这一轮注入了什么」推给前端，让上下文可解释
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

    db.add_message(session_id, "user", user_message)
    if session["title"] == "新会话":
        db.update_session_title(session_id, user_message.strip()[:24] or "新会话")

    buffer: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    config = {"configurable": {"thread_id": session_id}}

    try:
        async for event in agent.astream_events(
            {"messages": [HumanMessage(content=user_message)]},
            config,
            version="v2",
        ):
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
    except Exception as exc:  # noqa: BLE001
        yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})
        return

    final_text = "".join(buffer)
    if final_text.strip():
        db.add_message(
            session_id,
            "assistant",
            final_text,
            meta={"tool_calls": tool_calls} if tool_calls else None,
        )
    yield _sse("done", {"chars": len(final_text), "fingerprint": bundle.fingerprint})


def _truncate(value: Any, limit: int = 3000) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    return text[:limit]
