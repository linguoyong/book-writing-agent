from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_openai import ChatOpenAI

from ..config import load_settings
from ..workspace import read_book_meta
from .tools import SYSTEM_PROMPT, build_tools


def build_chat_model(role: str = "writer") -> ChatOpenAI:
    settings = load_settings()
    model_settings = settings.writer if role == "writer" else settings.extractor
    return ChatOpenAI(
        model=model_settings.model,
        api_key=model_settings.api_key or "not-needed",
        base_url=model_settings.base_url or None,
        temperature=model_settings.temperature,
        timeout=180,
        max_retries=2,
    )


def build_system_prompt(
    project: Path, style: str = "", readonly: bool = False, builder: str = ""
) -> str:
    meta = read_book_meta(project)
    progress = meta.get("progress") or {}
    chapter = progress.get("chapter", 1)
    volume = progress.get("volume", 1)
    title = meta.get("title") or project.name
    style_line = f"\n写作风格偏好：{style}。请在续写与改写时严格遵循。\n" if style else ""
    side_line = (
        "\n这是一次侧问：只需检索资料并给出简明回答，"
        "不要写入或修改任何文件，回答会展示在侧栏。\n"
        if readonly
        else ""
    )
    builder_line = ""
    if builder == "expert":
        builder_line = (
            "\n你正在与用户一起创建一个写作专家。请通过提问确认：擅长领域、叙事风格、"
            "工作流程、禁忌事项。信息足够后调用 expert_write 保存；expert_id 用简短英文或拼音，"
            "name 用中文。不要编造用户偏好，不确定就问。保存后告诉用户可在专家页选中并设为当前专家。\n"
        )
    elif builder == "skill":
        builder_line = (
            "\n你正在创建一个技能。请确认：技能用途、触发场景、执行步骤、输出格式。"
            "确认后调用 skill_write 保存，技能名用中文，说明要具体可执行。\n"
        )
    return (
        f"{SYSTEM_PROMPT}\n"
        f"当前书稿：《{title}》，进度：第{volume}卷第{chapter}章。\n"
        f"书稿根目录：{project}\n"
        f"{style_line}"
        f"{side_line}"
        f"{builder_line}"
    )


def build_agent(
    project: Path, style: str = "", readonly: bool = False, builder: str = ""
):  # noqa: ANN201
    settings = load_settings()
    tools: list[Any] = build_tools(project, settings.embedding, readonly=readonly)
    backend = FilesystemBackend(root_dir=str(project), virtual_mode=True)
    return create_deep_agent(
        model=build_chat_model("writer"),
        tools=tools,
        system_prompt=build_system_prompt(project, style, readonly, builder),
        backend=backend,
        interrupt_on={"kb_write": False, "manuscript_write": False},
        name="writing-agent",
    )
