from __future__ import annotations

import re

from .llm import build_chat_model

MAX_INPUT = 4000
MAX_CONTEXT = 600

ACTIONS = {
    "polish": "润色：保留原意与信息量，改善节奏、用词与句子长短，不要增删情节。",
    "expand": "扩写：补充动作、细节或环境描写，篇幅约为原来的 1.6 倍，不引入新事件、不改变事实。",
    "shorten": "压缩：保留关键动作与信息，去掉冗余修饰，篇幅约为原来的 0.6 倍。",
    "tone": "调整语气：保持事实不变，按要求的语气重写。",
}

SYSTEM = """你是一位中文小说编辑，只负责改写给定的片段。
要求：
1. 只输出改写后的正文，不要解释、不要加标题、不要用代码块包裹。
2. 保持人称、时态、专有名词（人名、地名、术语）不变。
3. 保持段落划分，不要合并成一大段。
4. 不要引入原文没有的事件、角色或设定。"""


class RewriteError(RuntimeError):
    """改写失败，消息可直接展示给用户。"""


def _clean(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```[a-zA-Z]*\s*\n(.*)\n```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    text = re.sub(r"^(改写|润色|结果)[:：]\s*", "", text)
    return text.strip()


def rewrite(
    text: str,
    *,
    action: str = "polish",
    tone: str = "",
    before: str = "",
    after: str = "",
) -> dict[str, str]:
    text = (text or "").strip()
    if not text:
        raise RewriteError("没有选中文字")
    if len(text) > MAX_INPUT:
        raise RewriteError(f"选中内容过长（{len(text)} 字），请分段改写")

    instruction = ACTIONS.get(action) or ACTIONS["polish"]
    if action == "tone" and tone.strip():
        instruction = f"调整语气为「{tone.strip()}」：保持事实不变，重写这一段。"
    elif action == "tone":
        raise RewriteError("调整语气需要指定目标语气")

    parts = [SYSTEM, f"任务：{instruction}"]
    if before.strip():
        parts.append(f"上文（仅供理解，不要改写）：\n{before.strip()[-MAX_CONTEXT:]}")
    if after.strip():
        parts.append(f"下文（仅供理解，不要改写）：\n{after.strip()[:MAX_CONTEXT]}")
    parts.append(f"需要改写的片段：\n{text}")
    parts.append("直接输出改写后的片段：")

    model = build_chat_model("writer")
    try:
        message = model.invoke("\n\n".join(parts))
    except Exception as exc:  # noqa: BLE001 - 模型侧异常统一转成可读错误
        raise RewriteError(f"模型调用失败：{type(exc).__name__}: {exc}") from exc

    content = getattr(message, "content", "")
    if isinstance(content, list):
        content = "".join(str(item) for item in content)
    result = _clean(str(content))
    if not result:
        raise RewriteError("模型没有返回内容")
    return {"text": result, "action": action}
