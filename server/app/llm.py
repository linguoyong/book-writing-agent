from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import openai
from langchain_core.exceptions import ContextOverflowError
from langchain_openai import ChatOpenAI

from .config import load_settings

# DeepSeek 目前只提供两档窗口，其它值一律归一到最近的档位
WINDOW_CHOICES = (500_000, 1_000_000)

# 各家「超窗口」的报错文案不统一：OpenAI 用 context_length_exceeded，
# DeepSeek 用 "maximum context length is N tokens"，xAI 用 "prompt is too long"。
# langchain-openai 只认前两类里的一部分，其余会被当成普通 400 抛出去，
# 自动压缩就永远不会触发。这里统一转成 ContextOverflowError。
_OVERFLOW_HINTS = (
    "context_length_exceeded",
    "maximum context length",
    "context length",
    "prompt is too long",
    "input tokens exceed",
    "contextwindowexceeded",
    "too many tokens",
    "reduce the length of the messages",
)


def normalize_window(value: int | None) -> int:
    if not value or value <= 0:
        return WINDOW_CHOICES[0]
    return 1_000_000 if value >= 1_000_000 else 500_000


def _as_overflow(exc: openai.BadRequestError) -> Exception:
    text = f"{exc.message} {exc.body}".lower()
    if any(hint in text for hint in _OVERFLOW_HINTS):
        return ContextOverflowError(exc.message)
    return exc


class BookChatModel(ChatOpenAI):
    """OpenAI 兼容客户端 + 超窗口错误归一化。

    deepagents 的压缩中间件靠捕获 ContextOverflowError 触发「先摘要再重试」，
    所以必须在模型层把各家的 400 文案翻译成同一个异常。
    """

    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return super()._generate(*args, **kwargs)
        except openai.BadRequestError as exc:
            raise _as_overflow(exc) from exc

    async def _agenerate(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return await super()._agenerate(*args, **kwargs)
        except openai.BadRequestError as exc:
            raise _as_overflow(exc) from exc

    def _stream(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        try:
            yield from super()._stream(*args, **kwargs)
        except openai.BadRequestError as exc:
            raise _as_overflow(exc) from exc

    async def _astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        try:
            async for chunk in super()._astream(*args, **kwargs):
                yield chunk
        except openai.BadRequestError as exc:
            raise _as_overflow(exc) from exc


def build_chat_model(role: str = "writer") -> ChatOpenAI:
    """统一模型入口。writer 用于对话与写作，extractor 用于抽取与记忆提炼。"""
    settings = load_settings()
    model_settings = settings.writer if role == "writer" else settings.extractor
    window = normalize_window(model_settings.context_window)
    model = BookChatModel(
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
