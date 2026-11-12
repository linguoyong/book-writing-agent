from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import openai
from langchain_core.exceptions import ContextOverflowError
from langchain_openai import ChatOpenAI

from .config import ModelProfile, ModelSettings, load_settings, resolve_model

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


# 明确不支持 stream_options 的端点：记住之后，后续请求不再带这个字段，
# 避免每轮都先吃一次 400。
_NO_STREAM_USAGE: set[str] = set()


def _usage_key(base_url: str | None, model: str) -> str:
    return f"{base_url or ''}|{model}"


def _is_stream_options_error(exc: openai.APIStatusError) -> bool:
    text = f"{getattr(exc, 'message', '')} {getattr(exc, 'body', '')}".lower()
    return "stream_options" in text or "include_usage" in text


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
        yielded = False
        try:
            for chunk in super()._stream(*args, **kwargs):
                yielded = True
                yield chunk
        except openai.APIStatusError as exc:
            if not yielded and self.stream_usage and _is_stream_options_error(exc):
                # 端点不认识 stream_options：关掉它重试一次，并记住这个端点
                self.stream_usage = False
                _NO_STREAM_USAGE.add(_usage_key(self.openai_api_base, self.model_name))
                yield from super()._stream(*args, **kwargs)
                return
            if isinstance(exc, openai.BadRequestError):
                raise _as_overflow(exc) from exc
            raise

    async def _astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        yielded = False
        try:
            async for chunk in super()._astream(*args, **kwargs):
                yielded = True
                yield chunk
        except openai.APIStatusError as exc:
            if not yielded and self.stream_usage and _is_stream_options_error(exc):
                self.stream_usage = False
                _NO_STREAM_USAGE.add(_usage_key(self.openai_api_base, self.model_name))
                async for chunk in super()._astream(*args, **kwargs):
                    yield chunk
                return
            if isinstance(exc, openai.BadRequestError):
                raise _as_overflow(exc) from exc
            raise


def build_chat_model(role: str = "writer", model_id: str | None = None) -> ChatOpenAI:
    """统一模型入口。

    - writer：按 `model_id`（会话级）或全局 active_model_id 取模型配置；
    - extractor：用独立的抽取模型配置（导入/记忆提炼）；
    - reviewer：用独立的审稿模型配置，未配置时回退到 active 模型。
    """
    settings = load_settings()
    if role == "extractor":
        source = settings.extractor
        output = 8192
    elif role == "reviewer" and settings.reviewer.model:
        source = settings.reviewer
        output = 16384
    else:
        source = resolve_model(settings, model_id)
        output = source.max_output_tokens

    return chat_model_from_settings(source, output_tokens=output)


def chat_model_from_settings(
    source: ModelSettings | ModelProfile,
    *,
    output_tokens: int = 8192,
    timeout: float = 180,
    max_retries: int = 2,
    http_client: httpx.Client | None = None,
    http_async_client: httpx.AsyncClient | None = None,
) -> ChatOpenAI:
    """用同一套兼容规则构造模型，也供未保存配置的连接测试使用。"""
    key = _usage_key(source.base_url or None, source.model)
    extra: dict[str, Any] = {}
    effort = str(getattr(source, "reasoning_effort", "") or "").strip()
    if effort:
        # 走 extra_body 而不是构造参数：不同 langchain-openai 版本对
        # reasoning_effort 的字段支持不一致，直接塞进请求体最稳。
        extra["extra_body"] = {"reasoning_effort": effort}
    model = BookChatModel(
        model=source.model,
        api_key=source.api_key or "not-needed",
        base_url=source.base_url or None,
        temperature=source.temperature,
        timeout=timeout,
        max_retries=max_retries,
        http_client=http_client,
        http_async_client=http_async_client,
        # 自定义 base_url 时 langchain 默认不请求 usage，用量页会整轮记 0。
        # 主动打开；遇到不支持的端点会在首次 400 后自动降级。
        stream_usage=key not in _NO_STREAM_USAGE,
        **extra,
    )
    # 窗口与输出预算交给中间件折算压缩阈值；不硬塞 max_tokens，
    # 避免不同服务商对超上限的 max_tokens 直接返回 400。
    model.profile = {
        "max_input_tokens": normalize_window(source.context_window),
        "max_output_tokens": output_tokens,
    }
    return model
