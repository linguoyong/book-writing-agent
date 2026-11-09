from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend

from ..config import APP_HOME, GLOBAL_SKILLS_DIR, load_settings
from ..context import ContextBundle, assemble, tool_context
from ..domains import get_domain
from ..llm import build_chat_model, normalize_window
from ..sandbox import compile_permissions
from .approvals import GATED_TOOLS
from .backend import ProjectFilesystemBackend
from .checkpointer import get_checkpointer
from .compaction import build_compaction
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
    extra_tools: list[Any] | None = None,
    parent_messages: list[dict[str, Any]] | None = None,
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
        parent_messages=parent_messages,
    )
    domain = get_domain(bundle.domain_id)
    ctx = tool_context(
        project,
        project_id=project_id or (session or {}).get("project_id", ""),
        session_id=(session or {}).get("id", ""),
        readonly=readonly,
    )
    tools = domain.build_tools(ctx)
    if extra_tools:
        # MCP 工具：只读侧问不注入（见 runner），名字已带服务器前缀
        tools = [*tools, *extra_tools]
    backend = _backend(project)
    skills = _skill_sources(project, domain.skills_subdir)
    settings = load_settings()
    mode = (session or {}).get("permission_mode") or settings.sandbox.default_mode
    # 审批模式下，写工具与通用文件写入都要人工确认；完全访问模式跳过审批，但规则 deny 仍生效
    interrupt_on = None if readonly or mode == "auto" else {name: True for name in GATED_TOOLS}
    if readonly:
        # 侧问是只读会话：权限栈最前面兜一条全盘写 deny。
        # deepagents 内置的 write_file / edit_file / delete 不受自研工具集约束，
        # 只传 permissions=None 等于全放行；这里连规则里的 deny（.env、私钥）一起保留。
        permissions = [
            FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
            *compile_permissions(settings.sandbox, mode="auto"),
        ]
    else:
        permissions = compile_permissions(settings.sandbox, mode=mode)

    sync_session = (session or {}).get("id", "")
    model = build_chat_model("writer", (session or {}).get("model_id"))
    window = normalize_window(model.profile.get("max_input_tokens") if model.profile else None)
    middleware: list[Any] = [build_compaction(model, backend, window=window)]
    if sync_session:
        middleware.insert(0, SteeringMiddleware(sync_session))

    agent = create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=bundle.system_prompt,
        backend=backend,
        skills=skills,
        permissions=permissions,
        middleware=middleware,
        checkpointer=get_checkpointer(),
        interrupt_on=interrupt_on,
        name=f"agent-{domain.id}",
    )
    return agent, bundle


def _backend(project: Path) -> CompositeBackend:
    """项目根目录为主，全局技能挂 /global-skills，压缩产物挂 /artifacts。"""
    default = ProjectFilesystemBackend(root_dir=str(project), virtual_mode=True)
    routes: dict[str, FilesystemBackend] = {}
    if GLOBAL_SKILLS_DIR.exists():
        routes["/global-skills/"] = FilesystemBackend(
            root_dir=str(GLOBAL_SKILLS_DIR), virtual_mode=True
        )
    # 自动压缩会把淘汰的完整对话落盘。默认 artifacts_root="/" 会把
    # conversation_history/ 写进书稿根目录，被 git add -A 带进版本库；
    # 这里改挂到 ~/.book-agent/artifacts，书稿目录只留正文与设定。
    artifacts = APP_HOME / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    routes["/artifacts/"] = FilesystemBackend(root_dir=str(artifacts), virtual_mode=True)
    return CompositeBackend(default=default, routes=routes, artifacts_root="/artifacts")


def _skill_sources(project: Path, subdir: str) -> list[str] | None:
    sources: list[str] = []
    root = project / subdir
    if root.exists() and any(root.glob("*/SKILL.md")):
        sources.append(f"/{subdir}")
    if GLOBAL_SKILLS_DIR.exists() and any(GLOBAL_SKILLS_DIR.glob("*/SKILL.md")):
        sources.append("/global-skills")
    return sources or None
