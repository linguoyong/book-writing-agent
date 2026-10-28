from __future__ import annotations

from langchain_openai import ChatOpenAI

from .config import load_settings

# DeepSeek 目前只提供两档窗口，其它值一律归一到最近的档位
WINDOW_CHOICES = (500_000, 1_000_000)


def normalize_window(value: int | None) -> int:
    if not value or value <= 0:
        return WINDOW_CHOICES[0]
    return 1_000_000 if value >= 1_000_000 else 500_000


def build_chat_model(role: str = "writer") -> ChatOpenAI:
    """统一模型入口。writer 用于对话与写作，extractor 用于抽取与记忆提炼。"""
    settings = load_settings()
    model_settings = settings.writer if role == "writer" else settings.extractor
    window = normalize_window(model_settings.context_window)
    model = ChatOpenAI(
        model=model_settings.model,
        api_key=model_settings.api_key or "not-needed",
        base_url=model_settings.base_url or None,
        temperature=model_settings.temperature,
        timeout=180,
        max_retries=2,
    )
    # 把窗口大小告诉中间件：deepagents 据此折算压缩阈值，
    # 子 agent 也会读到同一份 profile。
    model.profile = {"max_input_tokens": window, "max_output_tokens": 8192}
    return model
