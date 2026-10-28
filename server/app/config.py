from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

APP_HOME = Path(os.environ.get("BOOK_AGENT_HOME", Path.home() / ".book-agent"))
CONFIG_FILE = APP_HOME / "config.json"
DB_FILE = APP_HOME / "app.db"
BOOKS_DIR = APP_HOME / "books"


class ModelSettings(BaseModel):
    base_url: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    model: str = "deepseek-chat"
    temperature: float = 0.7


class EmbeddingSettings(BaseModel):
    provider: str = "none"  # none | openai
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "bge-m3"
    dimensions: int = 1024


class Settings(BaseModel):
    writer: ModelSettings = Field(
        default_factory=lambda: ModelSettings(model="deepseek-chat")
    )
    extractor: ModelSettings = Field(
        default_factory=lambda: ModelSettings(model="deepseek-chat", temperature=0.1)
    )
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)


def _ensure_home() -> None:
    APP_HOME.mkdir(parents=True, exist_ok=True)
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)


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
