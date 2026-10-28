from __future__ import annotations

from langchain_openai import ChatOpenAI

from .config import load_settings


def build_chat_model(role: str = "writer") -> ChatOpenAI:
    """统一模型入口。writer 用于对话与写作，extractor 用于抽取与记忆提炼。"""
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
