from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import openai
from langchain_core.exceptions import ContextOverflowError
from langchain_openai import ChatOpenAI

from .config import load_settings, resolve_model

# 模型窗口不再限定两档：默认 1M，允许 8K–4M 的自定义值
WINDOW_DEFAULT = 1_000_000
WINDOW_MIN = 8_000
WINDOW_MAX = 4_000_000

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
        return WINDOW_DEFAULT
    return max(WINDOW_MIN, min(int(value), WINDOW_MAX))


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


def build_chat_model(role: str = "writer", model_id: str | None = None) -> ChatOpenAI:
    """统一模型入口。

    - writer：按 `model_id`（会话级）或全局 active_model_id 取模型配置；
    - extractor：仍用独立的抽取模型配置（导入/记忆提炼）。
    """
    settings = load_settings()
    if role == "extractor":
        source = settings.extractor
        window = normalize_window(source.context_window)
        output = 8192
    else:
        source = resolve_model(settings, model_id)
        window = normalize_window(source.context_window)
        output = source.max_output_tokens

    model = BookChatModel(
        model=source.model,
        api_key=source.api_key or "not-needed",
        base_url=source.base_url or None,
        temperature=source.temperature,
        timeout=180,
        max_retries=2,
    )
    # 窗口与输出预算交给中间件折算压缩阈值；不硬塞 max_tokens，
    # 避免不同服务商对超上限的 max_tokens 直接返回 400。
    model.profile = {"max_input_tokens": window, "max_output_tokens": output}
    return model
