from __future__ import annotations

import json
import os
from pathlib import Path

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .sandbox import SandboxSettings

APP_HOME = Path(os.environ.get("BOOK_AGENT_HOME", Path.home() / ".book-agent"))
CONFIG_FILE = APP_HOME / "config.json"
DB_FILE = APP_HOME / "app.db"
BOOKS_DIR = APP_HOME / "books"
MEMORY_DIR = APP_HOME / "memory"
GLOBAL_SKILLS_DIR = APP_HOME / "skills"
DAILY_LOG_DIR = MEMORY_DIR


class ModelSettings(BaseModel):
    base_url: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    model: str = "deepseek-flash"
    temperature: float = 0.7
    # 模型上下文窗口（token）。只影响上下文装配预算与自动压缩阈值，
    # 不会改变服务端真实上限。
    context_window: int = 1_000_000


class ModelProfile(BaseModel):
    """可切换的模型来源：一个 base_url + key + 模型名 + 窗口预算。"""

    id: str
    name: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    context_window: int = 1_000_000
    max_output_tokens: int = 64_000
    temperature: float = 0.7

    @field_validator("id")
    @classmethod
    def _clean_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("模型 id 不能为空")
        return cleaned

    @field_validator("context_window")
    @classmethod
    def _window_floor(cls, value: int) -> int:
        return max(8_000, min(int(value or 1_000_000), 4_000_000))

    @field_validator("max_output_tokens")
    @classmethod
    def _output_floor(cls, value: int) -> int:
        return max(512, min(int(value or 64_000), 200_000))


class EmbeddingSettings(BaseModel):
    # none：只用 FTS5 关键词检索；local：本地 ONNX 模型；openai：OpenAI 兼容 /embeddings
    provider: str = "none"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "bge-m3"
    dimensions: int = 0  # 仅作提示，实际维度以模型返回为准
    local_model: str = "BAAI/bge-small-zh-v1.5"


class McpServerSettings(BaseModel):
    """一个 MCP 服务器：stdio（本地命令）或 http（streamable http）。"""

    name: str
    transport: Literal["stdio", "http"] = "stdio"
    command: str = ""  # stdio：可执行文件
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""  # http：端点
    enabled: bool = True


class Settings(BaseModel):
    # 可切换的模型来源；为空时由旧 writer 配置自动生成一条
    models: list[ModelProfile] = Field(default_factory=list)
    active_model_id: str = ""
    writer: ModelSettings = Field(
        default_factory=lambda: ModelSettings(model="deepseek-flash")
    )
    extractor: ModelSettings = Field(
        default_factory=lambda: ModelSettings(model="deepseek-flash", temperature=0.1)
    )
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    mcp: list[McpServerSettings] = Field(default_factory=list)


def ensure_models(settings: Settings) -> Settings:
    """保证至少有一个可用模型，并把 active 指到存在的项。"""
    if not settings.models:
        writer = settings.writer
        settings.models = [
            ModelProfile(
                id="default",
                name=writer.model or "默认模型",
                base_url=writer.base_url,
                api_key=writer.api_key,
                model=writer.model or "deepseek-flash",
                context_window=writer.context_window or 1_000_000,
                max_output_tokens=64_000,
                temperature=writer.temperature,
            )
        ]
    ids = {item.id for item in settings.models}
    if settings.active_model_id not in ids:
        settings.active_model_id = settings.models[0].id
    return settings


def resolve_model(
    settings: Settings | None = None, model_id: str | None = None
) -> ModelProfile:
    settings = ensure_models(settings or load_settings())
    if model_id:
        for item in settings.models:
            if item.id == model_id:
                return item
    for item in settings.models:
        if item.id == settings.active_model_id:
            return item
    return settings.models[0]


def _ensure_home() -> None:
    APP_HOME.mkdir(parents=True, exist_ok=True)
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    GLOBAL_SKILLS_DIR.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    _ensure_home()
    if not CONFIG_FILE.exists():
        settings = ensure_models(Settings())
        save_settings(settings)
        return settings
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return ensure_models(Settings.model_validate(raw))
    except (json.JSONDecodeError, ValueError):
        return ensure_models(Settings())


def save_settings(settings: Settings) -> None:
    _ensure_home()
    CONFIG_FILE.write_text(
        ensure_models(settings).model_dump_json(indent=2), encoding="utf-8"
    )
