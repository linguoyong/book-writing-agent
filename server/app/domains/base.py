from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..config import EmbeddingSettings


@dataclass
class ToolContext:
    """工具运行的上下文：内核只负责传，域包自己决定怎么用。"""

    project: Path
    embedding: EmbeddingSettings
    project_id: str = ""
    session_id: str = ""
    readonly: bool = False


class DomainPack(Protocol):
    """域包协议。一个新领域只需要实现这五项，即可接入内核。"""

    id: str
    name: str
    description: str
    persona: str
    rules: str
    skills_subdir: str

    def build_tools(self, ctx: ToolContext) -> list[Any]:
        ...


@dataclass
class SimpleDomain:
    id: str
    name: str
    description: str
    persona: str = ""
    rules: str = ""
    skills_subdir: str = "skills"
    tool_builder: Any = None
    meta: dict[str, Any] = field(default_factory=dict)

    def build_tools(self, ctx: ToolContext) -> list[Any]:
        if self.tool_builder is None:
            return []
        return list(self.tool_builder(ctx))
