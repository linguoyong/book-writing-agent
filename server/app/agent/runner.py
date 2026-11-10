from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai.chat_models._client_utils import StreamChunkTimeoutError
from langgraph.types import Command

from .. import db, usage
from ..config import load_settings
from ..workspace import safe_join, turn_changes
from . import steering, threads
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


# LangGraph 默认 25 步就要停；写作场景一轮里连续十几次工具调用很正常
# （截图里就出现过 project_overview → chapter_list → ls ×3 → kb_list → kb_get ×4）。
# 120 步约等于 60 次工具调用，够用且仍能挡住真死循环。
RECURSION_LIMIT = 120


def _error_text(exc: BaseException) -> str:
    """把框架异常翻译成用户能看懂的话。"""
    if isinstance(exc, StreamChunkTimeoutError):
        return (
            f"模型连续 {exc.timeout_s:g} 秒没有返回新数据，生成超时。"
            "已完成的操作和已生成的内容已保留，可以稍后继续。"
        )
    if type(exc).__name__ == "GraphRecursionError":
        return (
            f"这一轮工具调用步数到上限了（{RECURSION_LIMIT} 步），先停下。"
            "可以说「继续」让我接着做，或者把任务拆小一点。"
        )
    return f"{type(exc).__name__}: {exc}"


def _failure(exc: BaseException) -> dict[str, str]:
    return {"message": _error_text(exc), "code": type(exc).__name__}


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
    thread_id = threads.session_thread(session, session_id)
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}
    started = time.monotonic()
    request_started = started
    round_started = time.time() * 1000
    # 已落库的字符数：正常路径每段落库后更新；finally 据此判断是否还有未落库内容
    committed = -1
    execution: dict[str, Any] = {"retries": 0}
    failure: dict[str, str] | None = None

    lock = _session_lock(session_id)
    if lock.locked():
        yield _sse("error", {"message": "当前会话正在生成，请等这一轮结束或先停止。"})
        return
    await lock.acquire()
    try:
        steering.begin(session_id)
        # 用户消息先落库，初始化模型或 MCP 期间切走也能恢复这一轮的请求。
        if persist_user:
            await asyncio.to_thread(
                db.add_message,
                session_id,
                "user",
                user_message,
                meta={"references": references} if references else None,
            )
            if session["title"] == "新会话":
                db.update_session_title(session_id, user_message.strip()[:24] or "新会话")
        try:
            # MCP 工具在只读侧问里不注入：它们不经路径沙箱
            if readonly:
                mcp_tools = []
            else:
                try:
                    mcp_tools = await asyncio.wait_for(mcp_manager.get_tools(), timeout=15)
                except TimeoutError:
                    # 某个 MCP 服务器不响应时降级为「少一批工具」，不要连对话都起不来
                    mcp_tools = []
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
            failure = _failure(exc)
            yield _sse("error", failure)
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

        graph_input = (
            {"messages": _history_messages(history)}
            if history is not None
            else {"messages": [HumanMessage(content=user_message)]}
        )
        try:
            async for chunk in _execute(
                agent,
                graph_input,
                config,
                buffer,
                tool_calls,
                write_paths,
                meter,
                session_id=session_id,
                project=project,
                execution=execution,
            ):
                yield chunk
        except Exception as exc:  # noqa: BLE001
            failure = _failure(exc)
            yield _sse("error", failure)
            return

        # 引导消息可能晚于最后一次模型调用到达：当轮补一段跟进，避免留到无关的下一轮
        approval = await _approval_event(agent, config, session_id, project)
        if not approval:
            leftover = steering.drain(session_id)
            if leftover:
                follow = (
                    "[执行中排队、但在上一段生成结束前未被消费的引导。请据此补充或修正结论，"
                    "不要重复已经说过的内容]\n" + "\n".join(f"- {item}" for item in leftover)
                )
                try:
                    async for chunk in _execute(
                        agent,
                        {"messages": [HumanMessage(content=follow)]},
                        config,
                        buffer,
                        tool_calls,
                        write_paths,
                        meter,
                        session_id=session_id,
                        project=project,
                        execution=execution,
                    ):
                        yield chunk
                except Exception as exc:  # noqa: BLE001
                    failure = _failure(exc)
                    yield _sse("error", failure)
                    return
                approval = await _approval_event(agent, config, session_id, project)
        turn = await asyncio.to_thread(
            _persist_assistant,
            session_id,
            buffer,
            tool_calls,
            awaiting=bool(approval),
            round_started=round_started,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            changes=await asyncio.to_thread(turn_changes, project, sorted(write_paths)),
            usage_snapshot=meter.as_dict(),
            failure=failure,
            retries=execution["retries"],
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
                **turn,
                "steering_pending": steering.pending_count(session_id),
            },
        )
    finally:
        # 异常、客户端断开（CancelledError）时也要保住已生成的文本，
        # 否则用户看到的内容刷新后就消失了。
        try:
            text = "".join(buffer)
            if len(text) > committed and (text.strip() or tool_calls or failure):
                await asyncio.to_thread(
                    _persist_assistant,
                    session_id,
                    buffer,
                    tool_calls,
                    awaiting=False,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    changes=await asyncio.to_thread(turn_changes, project, sorted(write_paths)),
                    interrupted=True,
                    round_started=round_started,
                    usage_snapshot=meter.as_dict(),
                    failure=failure,
                    retries=execution["retries"],
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


async def approve_stream(session_id: str, decisions: list[dict[str, Any]]) -> AsyncIterator[str]:
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
    thread_id = threads.session_thread(session, session_id)
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}
    started = time.monotonic()
    request_started = started
    round_started = time.time() * 1000
    for message in reversed(db.list_messages(session_id)):
        meta = message.get("meta") or {}
        if message["role"] == "assistant" and (meta.get("turn") or {}).get("started_at"):
            round_started = meta["turn"]["started_at"]
            break
        if message["role"] == "user" and not meta.get("steering"):
            round_started = datetime.fromisoformat(message["created_at"]).timestamp() * 1000
            break
    committed = -1
    execution: dict[str, Any] = {"retries": 0}
    failure: dict[str, str] | None = None
    try:
        steering.begin(session_id)
        # 拿到锁之后再读一次：并发的另一个审批可能已经把它消费掉了
        pending = db.pending_approval(session_id)
        if not pending:
            yield _sse("error", {"message": "没有待审批的操作"})
            return

        normalized = _normalize_decisions(decisions)
        requested = pending["payload"].get("requests") or []
        expected = len(requested)
        if not normalized:
            yield _sse("error", {"message": "审批决定为空"})
            return
        if expected and len(normalized) != expected:
            yield _sse("error", {"message": f"审批数量不匹配：需要 {expected} 条决定"})
            return
        # 审批期间文件被改过：工具会拿同一份 args 对当前磁盘重放，
        # 卡片上展示的 diff 就失效了。宁可让用户重新发起一次。
        stale: list[str] = []
        for index, request in enumerate(requested):
            expected = request.get("mtime")
            if not expected:
                continue
            decision = normalized[index] if index < len(normalized) else {}
            if decision.get("type") == "reject":
                continue
            target = str(request.get("target") or "")
            try:
                current = int(safe_join(project, target).stat().st_mtime * 1000)
            except (OSError, ValueError):
                continue
            if abs(current - int(expected)) > 2:
                stale.append(target)
        if stale:
            yield _sse(
                "error",
                {
                    "message": "审批期间文件已被修改："
                    + "、".join(stale[:3])
                    + "；请重新发起这次写入"
                },
            )
            return

        # 批量审批的 resume 没有 response_schema 兜底，工具名必须在这里钉死：
        # 否则「改参数」可以把待审的 manuscript_write 换成任意工具（含 MCP）。
        for index, decision in enumerate(normalized):
            if decision["type"] != "edit":
                continue
            original = requested[index] if index < len(requested) else {}
            expected_name = str(original.get("name") or "")
            if expected_name and decision["edited_action"]["name"] != expected_name:
                yield _sse("error", {"message": "审批只能修改参数，不能更换工具"})
                return

        expert = resolve_expert(project, session.get("expert_id") or "general")
        try:
            try:
                mcp_tools = await asyncio.wait_for(mcp_manager.get_tools(), timeout=15)
            except TimeoutError:
                mcp_tools = []
            agent, _ = build_agent(
                project,
                session=session,
                expert=expert,
                project_id=session["project_id"],
                extra_tools=mcp_tools,
            )
        except Exception as exc:  # noqa: BLE001
            failure = _failure(exc)
            yield _sse("error", failure)
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
            async for chunk in _execute(
                agent,
                Command(resume={"decisions": normalized}),
                config,
                buffer,
                tool_calls,
                write_paths,
                meter,
                session_id=session_id,
                project=project,
                execution=execution,
                resolution=(status, normalized),
            ):
                yield chunk
        except Exception as exc:  # noqa: BLE001
            # resume 失败时审批必须留在 pending：否则界面显示「已通过」，
            # 实际一次都没执行，而会话已经不再拦截下一条消息。
            failure = _failure(exc)
            yield _sse("error", failure)
            return

        # 恢复成功之后才记账
        approval = await _approval_event(agent, config, session_id, project)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        changes = await asyncio.to_thread(turn_changes, project, sorted(write_paths))
        turn = await asyncio.to_thread(
            _persist_assistant,
            session_id,
            buffer,
            tool_calls,
            awaiting=bool(approval),
            elapsed_ms=elapsed_ms,
            changes=changes,
            usage_snapshot=meter.as_dict(),
            failure=failure,
            retries=execution["retries"],
            round_started=round_started,
        )
        committed = len("".join(buffer))
        if approval:
            yield approval
        yield _sse(
            "done",
            {
                "chars": len("".join(buffer)),
                "awaiting_approval": bool(approval),
                **turn,
                "steering_pending": steering.pending_count(session_id),
            },
        )
    finally:
        # 与 chat_stream 对齐：审批通过后继续输出时断连，写入已落盘，
        # 已生成的文本也必须留住。
        try:
            text = "".join(buffer)
            if len(text) > committed and (text.strip() or tool_calls or failure):
                await asyncio.to_thread(
                    _persist_assistant,
                    session_id,
                    buffer,
                    tool_calls,
                    awaiting=False,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    changes=await asyncio.to_thread(turn_changes, project, sorted(write_paths)),
                    interrupted=True,
                    round_started=round_started,
                    usage_snapshot=meter.as_dict(),
                    failure=failure,
                    retries=execution["retries"],
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


async def _execute(
    agent: Any,
    graph_input: Any,
    config: dict[str, Any],
    buffer: list[str],
    tool_calls: list[dict[str, Any]],
    write_paths: set[str],
    meter: usage.UsageMeter,
    *,
    session_id: str,
    project: Path,
    resolution: tuple[str, list[dict[str, Any]]] | None = None,
    execution: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """保持同一张图，串行恢复完全访问下的每批中断，直到真正生成最终答复。"""
    execution = execution if execution is not None else {"retries": 0}
    for _ in range(RECURSION_LIMIT):
        before = (len(buffer), len(tool_calls))
        attempt: dict[str, Any] = {}
        try:
            async for chunk in _run_events(
                agent, graph_input, config, buffer, tool_calls, write_paths, meter, attempt
            ):
                yield chunk
        except StreamChunkTimeoutError:
            snapshot = await agent.aget_state(config)
            tasks = getattr(snapshot, "tasks", ()) or ()
            if (
                resolution
                and "offset" in attempt
                and len(tool_calls) > before[1]
                and all(call.get("status") == "done" for call in tool_calls[before[1] :])
            ):
                # 写入已执行、后续总结超时：这批审批已经消费，不能再展示为待审批。
                db.resolve_approvals(session_id, *resolution)
                resolution = None
            # 仅重跑已 checkpoint 的主模型节点，避免重放工具或子代理的写入。
            if (
                execution["retries"] >= 1
                or "offset" not in attempt
                or tuple(getattr(snapshot, "next", ())) != ("model",)
                or len(tasks) != 1
                or tasks[0].name != "model"
                or not tasks[0].error
                or getattr(snapshot, "interrupts", ())
            ):
                raise
            execution["retries"] += 1
            text = "".join(buffer)
            offset = attempt["offset"]
            buffer[:] = [text[:offset]] if offset else []
            yield _sse(
                "retry",
                {
                    "removed_chars": len(text) - offset,
                    "attempt": execution["retries"],
                    "message": "模型响应超时，正在重试（1/1）；已完成的操作已保留。",
                },
            )
            graph_input = None
            continue
        if resolution:
            if before == (len(buffer), len(tool_calls)):
                raise RuntimeError("审批恢复未产生执行结果，操作仍待审批，请重试或重新生成。")
            db.resolve_approvals(session_id, *resolution)
            resolution = None
        snapshot = await agent.aget_state(config)
        interrupts = getattr(snapshot, "interrupts", ()) or ()
        if not interrupts:
            final_offset = tool_calls[-1].get("offset", 0) if tool_calls else 0
            if not "".join(buffer)[final_offset:].strip():
                raise RuntimeError("本轮未生成最终答复，请继续执行或重试；已执行的工具结果已保留。")
            return
        session = db.get_session(session_id) or {}
        mode = session.get("permission_mode") or load_settings().sandbox.default_mode
        if mode != "auto":
            return
        interrupt = interrupts[0]
        requests = build_requests(project, interrupt.value)
        if not requests:
            raise RuntimeError("无法识别待审批操作，执行已暂停。")
        db.add_approval(session_id, getattr(interrupt, "id", None), {"requests": requests})
        decisions = [{"type": "approve"} for _ in requests]
        resolution = ("approved", decisions)
        graph_input = Command(resume={"decisions": decisions})
    raise RuntimeError("连续执行次数达到上限，请检查任务后继续。")


async def _run_events(
    agent: Any,
    graph_input: Any,
    config: dict[str, Any],
    buffer: list[str],
    tool_calls: list[dict[str, Any]],
    write_paths: set[str],
    meter: usage.UsageMeter,
    attempt: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    # 工具内部的审稿/拆解/记忆模型同样会产生模型流事件。
    # 只把主 Agent 的模型文本交给对话，工具和子代理的内部输出留在工具结果里。
    tool_runs: set[str] = set()

    async for event in agent.astream_events(graph_input, config, version="v2"):
        kind = event.get("event")
        name = event.get("name", "tool")
        run_id = str(event.get("run_id") or "")
        parents = {str(item) for item in (event.get("parent_ids") or [])}
        metadata = event.get("metadata") or {}
        internal = (
            bool(tool_runs & parents)
            or "book:internal" in (event.get("tags") or [])
            or bool(metadata.get("lc_internal_call"))
            or metadata.get("lc_source") == "summarization"
        )

        if kind == "on_chat_model_start" and not internal:
            if attempt is not None and metadata.get("langgraph_node") == "model":
                attempt["offset"] = sum(len(part) for part in buffer)
        elif kind == "on_chat_model_stream":
            if internal:
                continue
            text = _as_text(event.get("data", {}).get("chunk", {}).content)
            if text:
                buffer.append(text)
                yield _sse("token", {"text": text})
        elif kind == "on_chat_model_end":
            if not internal and attempt is not None:
                attempt.pop("offset", None)
            # 内部模型调用同样计费，单独记账的审稿/拆解在各业务函数中记录。
            if internal and "book:metered" in (event.get("tags") or []):
                continue
            meter.add(event.get("data", {}).get("output"))
        elif kind == "on_tool_start":
            if run_id:
                tool_runs.add(run_id)
            raw_input = event.get("data", {}).get("input", {})
            # 子代理的写入同样落到磁盘，本轮 diff 仍要统计
            if name in WRITE_TOOLS and isinstance(raw_input, dict):
                path = _write_path(name, raw_input)
                if path:
                    write_paths.add(path)
            if internal or name in {"write_todos"}:
                continue
            payload = {"name": name, "input": _truncate(raw_input)}
            tool_calls.append(
                {
                    "name": name,
                    "input": payload["input"],
                    "run_id": run_id,
                    "offset": sum(len(part) for part in buffer),
                    "status": "running",
                }
            )
            yield _sse("tool_start", payload)
        elif kind == "on_tool_end":
            if internal or name in {"write_todos"}:
                continue
            output = event.get("data", {}).get("output")
            content = getattr(output, "content", output)
            output_text = _truncate(content)
            for call in reversed(tool_calls):
                if call.get("run_id") == run_id:
                    call.update(output=output_text, status="done")
                    break
            yield _sse("tool_end", {"name": name, "output": output_text})


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
    record = db.add_approval(session_id, getattr(interrupt, "id", None), {"requests": requests})
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
    round_started: float | None = None,
    failure: dict[str, str] | None = None,
    retries: int = 0,
) -> dict[str, Any]:
    text = "".join(buffer)
    meta: dict[str, Any] = {}
    if tool_calls:
        meta["tool_calls"] = tool_calls
        trace: list[dict[str, Any]] = []
        cursor = 0
        for call in tool_calls:
            offset = max(cursor, min(len(text), int(call.get("offset", cursor))))
            if text[cursor:offset].strip():
                trace.append({"type": "text", "content": text[cursor:offset]})
            trace.append(
                {
                    "type": "tool",
                    "name": call["name"],
                    "input": call["input"],
                    "output": call.get("output", ""),
                    "status": call.get("status", "cancelled"),
                }
            )
            cursor = offset
        if text[cursor:].strip():
            trace.append({"type": "text", "content": text[cursor:]})
        meta["timeline"] = trace
        # 过程文本留在折叠轨迹中，供普通历史/回忆读取的 content 只存最终回答。
        text = text[cursor:]
    if awaiting:
        meta["awaiting_approval"] = True
    if interrupted:
        # 生成被中断（用户停止 / 连接断开 / 上游报错），文本仍保留
        meta["interrupted"] = True
    meta["turn"] = {
        "elapsed_ms": elapsed_ms,
        "changes": changes or {"files": [], "diff": "", "truncated": False},
        "phase_id": uuid4().hex,
        "status": "awaiting_approval"
        if awaiting
        else "interrupted"
        if interrupted
        else "completed",
    }
    if failure:
        meta["turn"]["error"] = failure
    if retries:
        meta["turn"]["retries"] = retries
    if round_started is not None:
        meta["turn"].update(
            started_at=round_started,
            elapsed_ms=max(elapsed_ms, int(time.time() * 1000 - round_started)),
            elapsed_scope="round",
        )
    # 用量写进消息里，刷新页面后轮次摘要仍能显示 token
    if usage_snapshot and (usage_snapshot.get("total") or usage_snapshot.get("calls")):
        meta["turn"]["usage"] = usage_snapshot
    db.add_message(session_id, "assistant", text, meta=meta)
    return meta["turn"]


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
