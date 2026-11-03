from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from .. import db, usage
from ..workspace import turn_changes
from . import steering
from .approvals import build_requests
from .factory import build_agent, resolve_expert
from .mcp_manager import manager as mcp_manager

MODE_BUILDER = {"expert_builder": "expert", "skill_builder": "skill"}

WRITE_TOOLS = {"kb_write", "manuscript_write", "write_file", "edit_file", "delete"}

# 同一会话同一时间只允许一个 run。没有这把锁时，双击发送、两个窗口、
# 「审批恢复」与「新消息」交叠都会让两个超步交错写同一份 checkpoint，
# 最坏的结果是同一章被 append 两遍。
_SESSION_LOCKS: dict[str, asyncio.Lock] = {}


def _session_lock(session_id: str) -> asyncio.Lock:
    lock = _SESSION_LOCKS.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _SESSION_LOCKS[session_id] = lock
    return lock


def _history_messages(records: list[dict[str, Any]]) -> list[Any]:
    """把已落库的消息还原成 LangChain 消息（重新生成时重放历史）。"""
    messages: list[Any] = []
    for item in records:
        content = str(item.get("content") or "")
        if not content.strip():
            continue
        if item.get("role") == "user":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))
    return messages


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
    parent_session_id: str | None = None,
    history: list[dict[str, Any]] | None = None,
    persist_user: bool = True,
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

    # 侧问：只读继承主会话最近几轮，理解当前在聊什么；不写回、不共用 thread
    parent_messages: list[dict[str, Any]] = []
    if readonly and parent_session_id and parent_session_id != session_id:
        if db.get_session(parent_session_id):
            parent_messages = [
                item
                for item in db.list_messages(parent_session_id, limit=8)
                if not (item.get("meta") or {}).get("steering")
            ]

    buffer: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    write_paths: set[str] = set()
    meter = usage.UsageMeter()
    thread_id = session.get("thread_id") or session_id
    config = {"configurable": {"thread_id": thread_id}}
    started = time.monotonic()
    request_started = started
    # 已落库的字符数：正常路径每段落库后更新；finally 据此判断是否还有未落库内容
    committed = 0

    lock = _session_lock(session_id)
    if lock.locked():
        yield _sse("error", {"message": "当前会话正在生成，请等这一轮结束或先停止。"})
        return
    await lock.acquire()
    try:
        steering.begin(session_id)
        try:
            # MCP 工具在只读侧问里不注入：它们不经路径沙箱
            mcp_tools = [] if readonly else await mcp_manager.get_tools()
            agent, bundle = build_agent(
                project,
                session=session,
                expert=expert,
                readonly=readonly,
                builder=builder,
                project_id=session["project_id"],
                references=references,
                parent_messages=parent_messages,
                extra_tools=mcp_tools,
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

        if persist_user:
            db.add_message(
                session_id,
                "user",
                user_message,
                meta={"references": references} if references else None,
            )
            if session["title"] == "新会话":
                db.update_session_title(session_id, user_message.strip()[:24] or "新会话")

        graph_input = (
            {"messages": _history_messages(history)}
            if history is not None
            else {"messages": [HumanMessage(content=user_message)]}
        )
        try:
            async for chunk in _run_events(
                agent,
                graph_input,
                config,
                buffer,
                tool_calls,
                write_paths,
                meter,
            ):
                yield chunk
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})
            return

        # 引导消息可能晚于最后一次模型调用到达：当轮补一段跟进，避免留到无关的下一轮
        approval = await _approval_event(agent, config, session_id, project)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        changes = await asyncio.to_thread(turn_changes, project, sorted(write_paths))
        _persist_assistant(
            session_id,
            buffer,
            tool_calls,
            awaiting=bool(approval),
            elapsed_ms=elapsed_ms,
            changes=changes,
            usage_snapshot=meter.as_dict(),
        )
        committed = len("".join(buffer))
        if approval:
            yield approval
        else:
            leftover = steering.drain(session_id)
            if leftover:
                follow = (
                    "[执行中排队、但在上一段生成结束前未被消费的引导。请据此补充或修正结论，"
                    "不要重复已经说过的内容]\n"
                    + "\n".join(f"- {item}" for item in leftover)
                )
                buffer.clear()
                tool_calls.clear()
                write_paths.clear()
                committed = 0
                started = time.monotonic()
                try:
                    async for chunk in _run_events(
                        agent,
                        {"messages": [HumanMessage(content=follow)]},
                        config,
                        buffer,
                        tool_calls,
                        write_paths,
                        meter,
                    ):
                        yield chunk
                except Exception as exc:  # noqa: BLE001
                    yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})
                approval = await _approval_event(agent, config, session_id, project)
                elapsed_ms = int((time.monotonic() - started) * 1000)
                changes = await asyncio.to_thread(turn_changes, project, sorted(write_paths))
                _persist_assistant(
                    session_id,
                    buffer,
                    tool_calls,
                    awaiting=bool(approval),
                    elapsed_ms=elapsed_ms,
                    changes=changes,
                    usage_snapshot=meter.as_dict(),
                )
                committed = len("".join(buffer))
                if approval:
                    yield approval
        yield _sse(
            "done",
            {
                "chars": len("".join(buffer)),
                "fingerprint": bundle.fingerprint,
                "awaiting_approval": bool(approval),
                "elapsed_ms": elapsed_ms,
                "changes": changes,
                "usage": meter.as_dict(),
                "steering_pending": steering.pending_count(session_id),
            },
        )
    finally:
        # 异常、客户端断开（CancelledError）时也要保住已生成的文本，
        # 否则用户看到的内容刷新后就消失了。
        try:
            text = "".join(buffer)
            if len(text) > committed and text.strip():
                _persist_assistant(
                    session_id,
                    buffer,
                    tool_calls,
                    awaiting=False,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    changes=await asyncio.to_thread(turn_changes, project, sorted(write_paths)),
                    interrupted=True,
                    usage_snapshot=meter.as_dict(),
                )
        finally:
            try:
                meter.flush(
                    project_id=session["project_id"],
                    session_id=session_id,
                    elapsed_ms=int((time.monotonic() - request_started) * 1000),
                )
            finally:
                steering.end(session_id)
                lock.release()


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

    lock = _session_lock(session_id)
    if lock.locked():
        yield _sse("error", {"message": "当前会话正在生成，请等这一轮结束或先停止。"})
        return
    await lock.acquire()

    buffer: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    write_paths: set[str] = set()
    meter = usage.UsageMeter()
    thread_id = session.get("thread_id") or session_id
    config = {"configurable": {"thread_id": thread_id}}
    started = time.monotonic()
    request_started = started
    committed = 0
    try:
        steering.begin(session_id)
        # 拿到锁之后再读一次：并发的另一个审批可能已经把它消费掉了
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
            mcp_tools = await mcp_manager.get_tools()
            agent, _ = build_agent(
                project,
                session=session,
                expert=expert,
                project_id=session["project_id"],
                extra_tools=mcp_tools,
            )
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": f"Agent 初始化失败：{type(exc).__name__}: {exc}"})
            return

        kinds = {item["type"] for item in normalized}
        if kinds == {"reject"}:
            status = "rejected"
        elif "reject" in kinds:
            # 一批写入里既有通过又有拒绝：不要笼统记成 approved
            status = "partial"
        else:
            status = "approved"

        try:
            async for chunk in _run_events(
                agent,
                Command(resume={"decisions": normalized}),
                config,
                buffer,
                tool_calls,
                write_paths,
                meter,
            ):
                yield chunk
        except Exception as exc:  # noqa: BLE001
            # resume 失败时审批必须留在 pending：否则界面显示「已通过」，
            # 实际一次都没执行，而会话已经不再拦截下一条消息。
            yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})
            return

        # 恢复成功之后才记账
        db.resolve_approvals(session_id, status, normalized)
        approval = await _approval_event(agent, config, session_id, project)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        changes = await asyncio.to_thread(turn_changes, project, sorted(write_paths))
        _persist_assistant(
            session_id,
            buffer,
            tool_calls,
            awaiting=bool(approval),
            elapsed_ms=elapsed_ms,
            changes=changes,
            usage_snapshot=meter.as_dict(),
        )
        committed = len("".join(buffer))
        if approval:
            yield approval
        yield _sse(
            "done",
            {
                "chars": len("".join(buffer)),
                "awaiting_approval": bool(approval),
                "elapsed_ms": elapsed_ms,
                "changes": changes,
                "usage": meter.as_dict(),
                "steering_pending": steering.pending_count(session_id),
            },
        )
    finally:
        # 与 chat_stream 对齐：审批通过后继续输出时断连，写入已落盘，
        # 已生成的文本也必须留住。
        try:
            text = "".join(buffer)
            if len(text) > committed and text.strip():
                _persist_assistant(
                    session_id,
                    buffer,
                    tool_calls,
                    awaiting=False,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    changes=await asyncio.to_thread(turn_changes, project, sorted(write_paths)),
                    interrupted=True,
                    usage_snapshot=meter.as_dict(),
                )
        finally:
            try:
                meter.flush(
                    project_id=session["project_id"],
                    session_id=session_id,
                    elapsed_ms=int((time.monotonic() - request_started) * 1000),
                )
            finally:
                steering.end(session_id)
                lock.release()


async def _run_events(
    agent: Any,
    graph_input: Any,
    config: dict[str, Any],
    buffer: list[str],
    tool_calls: list[dict[str, Any]],
    write_paths: set[str],
    meter: usage.UsageMeter,
) -> AsyncIterator[str]:
    # deepagents 默认挂一个 general-purpose 子代理，模型调 `task` 时
    # 子代理的模型流也会出现在 astream_events 里。不过滤的话，
    # 子代理的过程文本会拼进主回答、并写进消息历史。
    task_runs: set[str] = set()

    async for event in agent.astream_events(graph_input, config, version="v2"):
        kind = event.get("event")
        name = event.get("name", "tool")
        run_id = str(event.get("run_id") or "")
        parents = {str(item) for item in (event.get("parent_ids") or [])}
        # 只按「父链里含 task 工具 run」判定，判不出来时宁可不过滤，避免丢主回答
        in_subagent = bool(task_runs & parents)

        if kind == "on_chat_model_stream":
            if in_subagent:
                continue
            text = _as_text(event.get("data", {}).get("chunk", {}).content)
            if text:
                buffer.append(text)
                yield _sse("token", {"text": text})
        elif kind == "on_chat_model_end":
            # 子代理的调用同样计费，这里不做 in_subagent 过滤
            meter.add(event.get("data", {}).get("output"))
        elif kind == "on_tool_start":
            if name == "task" and run_id and not in_subagent:
                task_runs.add(run_id)
            raw_input = event.get("data", {}).get("input", {})
            # 子代理的写入同样落到磁盘，本轮 diff 仍要统计
            if name in WRITE_TOOLS and isinstance(raw_input, dict):
                path = _write_path(name, raw_input)
                if path:
                    write_paths.add(path)
            if in_subagent or name in {"write_todos"}:
                continue
            payload = {"name": name, "input": _truncate(raw_input)}
            tool_calls.append({"name": name, "input": payload["input"]})
            yield _sse("tool_start", payload)
        elif kind == "on_tool_end":
            if name == "task" and run_id:
                task_runs.discard(run_id)
            if in_subagent or name in {"write_todos"}:
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
        if kind not in {"approve", "reject", "edit"}:
            continue
        if kind == "edit":
            action = item.get("edited_action") or {}
            name = str(action.get("name") or "")
            args = action.get("args")
            if not name or not isinstance(args, dict):
                continue
            result.append({"type": "edit", "edited_action": {"name": name, "args": args}})
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
    elapsed_ms: int = 0,
    changes: dict[str, Any] | None = None,
    interrupted: bool = False,
    usage_snapshot: dict[str, Any] | None = None,
) -> None:
    text = "".join(buffer)
    if not text.strip():
        return
    meta: dict[str, Any] = {}
    if tool_calls:
        meta["tool_calls"] = tool_calls
    if awaiting:
        meta["awaiting_approval"] = True
    if interrupted:
        # 生成被中断（用户停止 / 连接断开 / 上游报错），文本仍保留
        meta["interrupted"] = True
    meta["turn"] = {
        "elapsed_ms": elapsed_ms,
        "changes": changes or {"files": [], "diff": "", "truncated": False},
    }
    # 用量写进消息里，刷新页面后轮次摘要仍能显示 token
    if usage_snapshot and (usage_snapshot.get("total") or usage_snapshot.get("calls")):
        meta["turn"]["usage"] = usage_snapshot
    db.add_message(session_id, "assistant", text, meta=meta)


def _write_path(name: str, args: dict[str, Any]) -> str | None:
    if name == "manuscript_write":
        relative = str(args.get("path") or "").strip().lstrip("/\\")
        return f"manuscript/{relative}" if relative else None
    if name == "kb_write":
        kind = str(args.get("kind") or "").strip()
        entity_id = str(args.get("entity_id") or "").strip()
        if not kind or not entity_id:
            return None
        return f"kb/{kind}/{entity_id}.md"
    if name in {"write_file", "edit_file", "delete"}:
        relative = str(args.get("file_path") or "").strip().lstrip("/\\")
        return relative.replace("\\", "/") if relative else None
    return None


def _truncate(value: Any, limit: int = 3000) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    return text[:limit]
