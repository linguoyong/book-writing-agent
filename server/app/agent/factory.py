from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from ..context import ContextBundle, assemble, tool_context
from ..domains import get_domain
from ..llm import build_chat_model
from .checkpointer import get_checkpointer


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
    )
    domain = get_domain(bundle.domain_id)
    ctx = tool_context(
        project,
        project_id=project_id or (session or {}).get("project_id", ""),
        session_id=(session or {}).get("id", ""),
        readonly=readonly,
    )
    tools = domain.build_tools(ctx)
    backend = FilesystemBackend(root_dir=str(project), virtual_mode=True)
    skills = _skill_sources(project, domain.skills_subdir)

    agent = create_deep_agent(
        model=build_chat_model("writer"),
        tools=tools,
        system_prompt=bundle.system_prompt,
        backend=backend,
        skills=skills,
        checkpointer=get_checkpointer(),
        # 逐条审批属于 P1′：前端还没有审批 UI，这里保持直写，避免断流无法恢复
        interrupt_on={"kb_write": False, "manuscript_write": False},
        name=f"agent-{domain.id}",
    )
    return agent, bundle


def _skill_sources(project: Path, subdir: str) -> list[str] | None:
    root = project / subdir
    if not root.exists():
        return None
    if not any(root.glob("*/SKILL.md")):
        return None
    return [f"/{subdir}"]
