from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend

from ..config import GLOBAL_SKILLS_DIR
from ..context import ContextBundle, assemble, tool_context
from ..domains import get_domain
from ..llm import build_chat_model
from .approvals import GATED_TOOLS
from .checkpointer import get_checkpointer
from .steering import SteeringMiddleware


def resolve_expert(project: Path, expert_id: str | None) -> dict[str, Any] | None:
    from ..experts import get_expert

    if not expert_id or expert_id == "none":
        return None
    return get_expert(project, expert_id)


def build_agent(
    project: Path,
    *,
    session: dict[str, Any] | None = None,
    expert: dict[str, Any] | None = None,
    readonly: bool = False,
    builder: str = "",
    project_id: str = "",
    references: list[dict[str, Any]] | None = None,
) -> tuple[Any, ContextBundle]:
    """装配一个带持久化会话状态的 agent。

    每轮重建图是廉价操作；真正的对话历史来自 checkpointer（thread_id = session_id），
    不再手工拼接消息列表。
    """
    bundle = assemble(
        project,
        session=session,
        expert=expert,
        readonly=readonly,
        builder=builder,
        references=references,
    )
    domain = get_domain(bundle.domain_id)
    ctx = tool_context(
        project,
        project_id=project_id or (session or {}).get("project_id", ""),
        session_id=(session or {}).get("id", ""),
        readonly=readonly,
    )
    tools = domain.build_tools(ctx)
    backend = _backend(project)
    skills = _skill_sources(project, domain.skills_subdir)
    # 只读会话没有写工具，无需拦截
    interrupt_on = None if readonly else {name: True for name in GATED_TOOLS}

    sync_session = (session or {}).get("id", "")
    middleware = [SteeringMiddleware(sync_session)] if sync_session else []

    agent = create_deep_agent(
        model=build_chat_model("writer"),
        tools=tools,
        system_prompt=bundle.system_prompt,
        backend=backend,
        skills=skills,
        middleware=middleware,
        checkpointer=get_checkpointer(),
        interrupt_on=interrupt_on,
        name=f"agent-{domain.id}",
    )
    return agent, bundle


def _backend(project: Path) -> CompositeBackend:
    """项目根目录为主，另挂全局技能到 /global-skills。"""
    default = FilesystemBackend(root_dir=str(project), virtual_mode=True)
    if not GLOBAL_SKILLS_DIR.exists():
        return CompositeBackend(default=default, routes={})
    return CompositeBackend(
        default=default,
        routes={
            "/global-skills/": FilesystemBackend(
                root_dir=str(GLOBAL_SKILLS_DIR), virtual_mode=True
            )
        },
    )


def _skill_sources(project: Path, subdir: str) -> list[str] | None:
    sources: list[str] = []
    root = project / subdir
    if root.exists() and any(root.glob("*/SKILL.md")):
        sources.append(f"/{subdir}")
    if GLOBAL_SKILLS_DIR.exists() and any(GLOBAL_SKILLS_DIR.glob("*/SKILL.md")):
        sources.append("/global-skills")
    return sources or None
