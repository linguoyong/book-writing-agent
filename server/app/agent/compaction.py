from __future__ import annotations

from typing import Any

from deepagents.backends.protocol import BackendProtocol
from deepagents.middleware.summarization import SummarizationMiddleware

from ..llm import normalize_window

# 压缩策略（质量优先）：
# - 触发点放到窗口的 60%，但硬顶 24 万 token。摘要一旦发生就会顶掉原文，
#   对写小说来说「原文记忆」比省 token 值钱，所以宁可让上下文长一点；
#   也不能真的等到 80%（50 万窗口就是 40 万）——那时候每轮重发几十万 token，
#   延迟和注意力质量都会明显变差。
# - 压缩后保留最近 30 条消息原文（约 8-10 轮），只把更早的部分摘要掉。
# - 先在 35% 处裁剪旧消息里的大参数（write_file / manuscript_write 的正文），
#   这一步只动旧工具参数、不动对话内容，属于无损的第一道闸。
TRIGGER_RATIO = 0.6
TRIGGER_CAP = 240_000
TRUNCATE_RATIO = 0.35
KEEP_MESSAGES = 30
SUMMARY_INPUT_TOKENS = 60_000

# 域定制摘要提示词：默认模板是通用 Agent 的，会漏掉「人物当前状态 / 设定口径 /
# 伏笔」这些续写最需要的东西。这里换成写作场景的交接单格式。
SUMMARY_PROMPT = """<role>
长篇小说写作助手的上下文压缩器
</role>

<objective>
下面的对话即将被这份摘要替换。请把它压缩成一份「续写交接单」：
让接手的自己只看摘要就能继续写，不重复已完成的工作，也不违背已有设定。
</objective>

<rules>
- 只记录对继续写这本书有用的信息，客套与探索过程不要写。
- 涉及人物状态、设定口径、关键台词时，尽量逐字保留原句，不要改写成概括。
- 不确定的内容标注「不确定」，不要脑补。
- 每条尽量带出处（第几章 / 哪个文件）。
</rules>

<sections>
## 会话意图
用户这一次想做什么，当前进行到哪一步。

## 已完成
已经写完/改完的东西，以及被否决的方案（含否决原因）。

## 人物与当前状态
出场人物的位置、处境、伤势、掌握的信息、关系变化。只写当前有效状态。

## 设定与口径
不可违背的世界观规则、称谓、地名、时间线锚点、数值设定。

## 伏笔
已埋下但还没回收的钩子，以及计划在哪回收。

## 文件改动
改过的文件路径，以及每个文件改了什么。

## 下一步
接着要做什么，按顺序列。
</sections>

用户会把完整对话发给你。请仔细读完，只输出上述摘要本身，不要任何前后缀说明。

<messages>
{messages}
</messages>
"""


def compaction_plan(window: int) -> dict[str, int]:
    """给前端 / 日志用的压缩参数一览。"""
    size = normalize_window(window)
    trigger = min(int(size * TRIGGER_RATIO), TRIGGER_CAP)
    # 截断阈值必须早于触发阈值，否则永远轮不到它生效
    truncate = min(int(size * TRUNCATE_RATIO), int(trigger * 0.7))
    return {
        "window": size,
        "trigger": trigger,
        "truncate": truncate,
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
        summary_prompt=SUMMARY_PROMPT,
        trim_tokens_to_summarize=SUMMARY_INPUT_TOKENS,
        truncate_args_settings={
            "trigger": ("tokens", plan["truncate"]),
            "keep": ("messages", KEEP_MESSAGES),
            "max_length": 3000,
            "truncation_text": " …（参数过长，旧消息中已截断）",
        },
    )
