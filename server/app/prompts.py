"""系统提示词各层的读写：把「代码里的默认值」变成「可编辑的文件」。

只有 identity / persona / domain 三层支持「恢复默认」——它们有代码里的兜底文案。
user / long / project 三层就是记忆文件本身（USER.md / MEMORY.md / AGENTS.md），
删掉等于清空用户的记忆，所以只给编辑、不给重置。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import memory
from .config import APP_HOME
from .text import read_text, save_text

PROMPTS_DIR = APP_HOME / "prompts"

# layer -> (中文名, 作用域, 是否可恢复默认)
LAYERS: dict[str, tuple[str, str, bool]] = {
    "identity": ("内核身份", "global", True),
    "persona": ("默认人格", "global", True),
    "domain": ("域规则", "project", True),
    "user": ("用户记忆", "global", False),
    "long": ("长期记忆", "global", False),
    "project": ("项目记忆", "project", False),
}


class PromptError(RuntimeError):
    """提示词读写失败，消息可直接展示。"""


def layer_path(layer: str, project: Path | None = None) -> Path:
    if layer not in LAYERS:
        raise PromptError(f"未知的提示词层：{layer}")
    if layer == "identity":
        return PROMPTS_DIR / "identity.md"
    if layer == "persona":
        return PROMPTS_DIR / "persona.md"
    if layer == "domain":
        if project is None:
            raise PromptError("域规则需要指定项目")
        return project / "prompts" / "domain.md"
    if layer == "user":
        return memory.memory_path("user")
    if layer == "long":
        return memory.memory_path("long")
    if project is None:
        raise PromptError("项目记忆需要指定项目")
    return memory.memory_path("project", project)


def default_content(layer: str, domain_id: str = "book") -> str:
    """代码里的兜底文案；记忆类返回种子模板。"""
    if layer == "identity":
        from .context import IDENTITY

        return IDENTITY
    if layer == "domain":
        from .domains import get_domain

        return get_domain(domain_id).rules
    if layer == "persona":
        from .domains import get_domain

        return get_domain(domain_id).persona
    if layer == "user":
        return memory.SEED_USER
    if layer == "long":
        return memory.SEED_LONG
    return ""


def read_layer(layer: str, project: Path | None = None, domain_id: str = "book") -> str:
    """读当前生效的内容：有覆盖文件就用覆盖，否则用默认值。"""
    if layer in {"user", "long", "project"}:
        # 记忆文件是「用进废退」的：没写过就先落种子，别让设置页显示成空白
        memory.ensure_files(project if layer == "project" else None)
    file = layer_path(layer, project)
    if file.exists():
        return read_text(file)
    return default_content(layer, domain_id)


def write_layer(layer: str, content: str, project: Path | None = None) -> Path:
    if layer not in LAYERS:
        raise PromptError(f"未知的提示词层：{layer}")
    file = layer_path(layer, project)
    file.parent.mkdir(parents=True, exist_ok=True)
    save_text(file, content)
    return file


def reset_layer(layer: str, project: Path | None = None) -> None:
    label, _scope, overridable = LAYERS[layer]
    if not overridable:
        raise PromptError(f"「{label}」是记忆文件，不能重置（会清空已有记忆）")
    file = layer_path(layer, project)
    if file.exists():
        file.unlink()


def describe(project: Path | None = None, domain_id: str = "book") -> list[dict[str, Any]]:
    """给设置页的清单：每层多大、预算多少、是否改过。"""
    from .context import LIMITS

    items: list[dict[str, Any]] = []
    for layer, (label, scope, overridable) in LAYERS.items():
        try:
            path = layer_path(layer, project)
        except PromptError:
            continue
        content = read_layer(layer, project, domain_id)
        items.append(
            {
                "layer": layer,
                "label": label,
                "scope": scope,
                "path": str(path),
                "chars": len(content),
                "limit": LIMITS.get(layer, 0),
                # 记忆文件本来就该和种子不同，只有覆盖型层才算「已自定义」
                "customized": overridable and path.exists(),
                "overridable": overridable,
                "exists": path.exists(),
            }
        )
    return items
