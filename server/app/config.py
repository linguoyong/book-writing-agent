from __future__ import annotations

import json
import os
from pathlib import Path

from typing import Literal

from pydantic import BaseModel, Field

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
    # 模型上下文窗口（token）。仅 DeepSeek 两个档位：500K / 1M。
    # 只影响上下文装配预算与自动压缩阈值，不会改变服务端真实上限。
    context_window: int = 500_000


class EmbeddingSettings(BaseModel):
    provider: str = "none"  # none | openai
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "bge-m3"
    dimensions: int = 1024


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
    writer: ModelSettings = Field(
        default_factory=lambda: ModelSettings(model="deepseek-flash")
    )
    extractor: ModelSettings = Field(
        default_factory=lambda: ModelSettings(model="deepseek-flash", temperature=0.1)
    )
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    mcp: list[McpServerSettings] = Field(default_factory=list)


def _ensure_home() -> None:
    APP_HOME.mkdir(parents=True, exist_ok=True)
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    GLOBAL_SKILLS_DIR.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    _ensure_home()
    if not CONFIG_FILE.exists():
        settings = Settings()
        save_settings(settings)
        return settings
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return Settings.model_validate(raw)
    except (json.JSONDecodeError, ValueError):
        return Settings()


def save_settings(settings: Settings) -> None:
    _ensure_home()
    CONFIG_FILE.write_text(
        settings.model_dump_json(indent=2), encoding="utf-8"
    )


def get_writer_model_settings() -> ModelSettings:
    return load_settings().writer
