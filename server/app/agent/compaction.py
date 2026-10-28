from __future__ import annotations

from typing import Any

from deepagents.backends.protocol import BackendProtocol
from deepagents.middleware.summarization import SummarizationMiddleware

from ..llm import normalize_window

# 压缩策略：到窗口的 80% 触发摘要，保留最近 12 条消息原文。
# 触发前先在 55% 处裁剪旧消息里的大参数（write_file / edit_file 正文），
# 往往能直接省出空间、避免真做一次摘要。
TRIGGER_RATIO = 0.8
TRUNCATE_RATIO = 0.55
KEEP_MESSAGES = 12
SUMMARY_INPUT_TOKENS = 60_000


def compaction_plan(window: int) -> dict[str, int]:
    """给前端 / 日志用的压缩参数一览。"""
    size = normalize_window(window)
    return {
        "window": size,
        "trigger": int(size * TRIGGER_RATIO),
        "truncate": int(size * TRUNCATE_RATIO),
        "keep_messages": KEEP_MESSAGES,
    }


def build_compaction(
    model: Any, backend: BackendProtocol, *, window: int
) -> SummarizationMiddleware:
    """构造自动压缩中间件。

    deepagents 默认会自己塞一个：有 profile 时按 85% / 10% 折算，
    没 profile 时硬编码 170k 触发。这里显式替换成按用户选择的窗口折算的版本，
    阈值可预测，也和上下文面板展示的数字对得上。
    """
    plan = compaction_plan(window)
    return SummarizationMiddleware(
        model=model,
        backend=backend,
        trigger=("tokens", plan["trigger"]),
        keep=("messages", KEEP_MESSAGES),
        trim_tokens_to_summarize=SUMMARY_INPUT_TOKENS,
        truncate_args_settings={
            "trigger": ("tokens", plan["truncate"]),
            "keep": ("messages", KEEP_MESSAGES),
            "max_length": 3000,
            "truncation_text": " …（参数过长，旧消息中已截断）",
        },
    )
