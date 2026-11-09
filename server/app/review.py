"""章节审稿：独立模型评判 + 原文证据校验 + 章节状态回写。

三条约束决定了这里的实现：

1. **只评判，不改稿**。审稿结果是一份问题清单，不是改写稿。改写仍然走
   `manuscript_write` 的审批通道，作者看得到 diff。
2. **每条问题必须有原文依据**。模型给出的 `quote` 必须能在正文里逐字找到，
   找不到就丢弃该条并计入 `dropped`——这是挡幻觉批评最有效的一层。
3. **结论进 front-matter，明细进 .index**。`review.status` 是事实（进 git），
   完整问题清单是过程产物（可清、可重跑）。

审稿用独立的模型来源（`settings.reviewer`），默认回退到 active 模型。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import usage
from .config import load_settings
from .context import LIMITS, assemble_review
from .export_book import chapter_files
from .fileops import body_hash, project_lock, write_project_text
from .kb.repository import dump_note, parse_note
from .llm import build_chat_model
from .text import read_text, save_text
from .workspace import read_book_meta, write_book_meta

REVIEW_DIR = ".index/reviews"
MAX_CHAPTER_CHARS = LIMITS["chapter"]
PASS_SCORE = 3.5
SEVERITIES = ("P0", "P1", "P2")
DIMENSIONS = ("consistency", "structure", "pacing", "voice", "hook", "redundancy")
DIMENSION_LABELS = {
    "consistency": "设定一致性",
    "structure": "结构完整性",
    "pacing": "节奏",
    "voice": "人物声音",
    "hook": "钩子与爽点",
    "redundancy": "文字冗余",
}

PROMPT = """请审阅下面这一章。

{context}

只输出一个 JSON 对象，不要 markdown 代码块，不要额外解释：

{{
  "dimensions": {{
    "consistency": 1,
    "structure": 1,
    "pacing": 1,
    "voice": 1,
    "hook": 1,
    "redundancy": 1
  }},
  "issues": [
    {{
      "severity": "P0",
      "dimension": "consistency",
      "quote": "本章正文里的逐字片段，不超过 60 字",
      "problem": "这里具体出了什么问题",
      "suggestion": "朝哪个方向改，不要写完整改写段落"
    }}
  ],
  "summary": "两三句话总评",
  "verdict": "pass"
}}

要求：
- dimensions 六项都要给 1-5 的整数分，5 最好。
- issues 按严重程度排序，最多 12 条；没有问题就给空数组。
- quote 必须从正文里逐字复制，不要改写、不要拼接两处。
- verdict 只能是 pass 或 fail；有 P0 时必须 fail。
- 用中文写 problem / suggestion / summary。"""


class ReviewError(RuntimeError):
    """审稿失败，消息可直接展示给用户。"""


@dataclass
class Issue:
    severity: str
    dimension: str
    quote: str
    problem: str
    suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def line(self) -> str:
        label = DIMENSION_LABELS.get(self.dimension, self.dimension)
        return f"[{self.severity}·{label}] {self.problem}\n  原文：{self.quote}\n  建议：{self.suggestion}"


@dataclass
class ReviewResult:
    status: str
    score: float
    dimensions: dict[str, int]
    issues: list[Issue] = field(default_factory=list)
    summary: str = ""
    verdict: str = "fail"
    model: str = ""
    reviewed_at: str = ""
    round: int = 1
    dropped: int = 0
    chapter: str = ""
    title: str = ""
    body_hash: str = ""
    reviewed_chars: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["issues"] = [item.to_dict() for item in self.issues]
        return data

    @property
    def p0(self) -> list[Issue]:
        return [item for item in self.issues if item.severity == "P0"]

    def brief(self) -> str:
        if self.status == "stale":
            return "审稿期间正文已修改，本次结果已保存为历史报告，请对当前正文重新审稿。"
        head = (
            f"审稿未通过（第 {self.round} 轮，{self.score:.1f} 分，"
            f"P0 {len(self.p0)} 条 / 共 {len(self.issues)} 条）"
            if self.status != "pass"
            else f"审稿通过（第 {self.round} 轮，{self.score:.1f} 分）"
        )
        lines = [head]
        if self.summary:
            lines.append(self.summary)
        lines.extend(item.line() for item in self.issues[:12])
        if self.dropped:
            lines.append(f"（另有 {self.dropped} 条因引用无法在正文定位而丢弃）")
        return "\n".join(lines)


# ---------------------------------------------------------------- 章节定位


def _normalize_target(target: str) -> str:
    return str(target or "").strip().replace("\\", "/").lstrip("/")


def find_chapter(project: Path, target: str) -> tuple[str, Path]:
    """把路径 / 章号 / 文件名统一成一个 manuscript 下的章节。

    支持：`vol-01/ch-003.md`、`ch-003.md`、`3`、`第3章`。
    """
    raw = _normalize_target(target)
    files = chapter_files(project)
    if not files:
        raise ReviewError("这本书还没有章节，先新建或导入正文")

    if raw.startswith("manuscript/"):
        raw = raw[len("manuscript/") :]

    for relative, file in files:
        if relative == raw or file.name == raw:
            return relative, file

    number = None
    match = re.search(r"(\d+)", raw)
    if match:
        number = int(match.group(1))
    if number is not None:
        matches: list[tuple[str, Path]] = []
        for relative, file in files:
            meta, _ = parse_note(read_text(file))
            try:
                chapter_no = int(meta.get("chapter") or 0)
            except (TypeError, ValueError):
                chapter_no = 0
            if chapter_no == number:
                matches.append((relative, file))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ReviewError(f"第 {number} 章在多个卷里重复，请用完整路径指定")

    raise ReviewError(f"找不到章节：{target}")


def load_chapter(project: Path, target: str) -> dict[str, Any]:
    relative, file = find_chapter(project, target)
    if not file.exists():
        raise ReviewError(f"章节文件不存在：{relative}")
    meta, body = parse_note(read_text(file))
    try:
        chapter_no = int(meta.get("chapter") or 0)
    except (TypeError, ValueError):
        chapter_no = 0
    return {
        "relative": relative,
        "file": file,
        "meta": meta,
        "body": body,
        "title": str(meta.get("title") or file.stem),
        "chapter": chapter_no,
        "review": meta.get("review") or {},
    }


def previous_tail(project: Path, relative: str, limit: int = 900) -> str:
    """上一章的结尾。跨卷也按排序取前一个，不按章号硬减。"""
    files = chapter_files(project)
    for index, (item_relative, _file) in enumerate(files):
        if item_relative != relative:
            continue
        if index == 0:
            return ""
        _, body = parse_note(read_text(files[index - 1][1]))
        text = body.strip()
        return text[-limit:] if len(text) > limit else text
    return ""


# ---------------------------------------------------------------- 调用模型


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReviewError(f"审稿模型返回的不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ReviewError("审稿模型返回的结构不对，应为 JSON 对象")
    return data


def _validate_result(data: dict[str, Any]) -> dict[str, int]:
    dimensions = data.get("dimensions")
    if not isinstance(dimensions, dict) or any(
        type(dimensions.get(key)) is not int or not 1 <= dimensions[key] <= 5 for key in DIMENSIONS
    ):
        raise ReviewError("审稿结果不完整：六项评分必须全部为 1–5 的整数，请重试")
    if data.get("verdict") not in ("pass", "fail"):
        raise ReviewError("审稿结论格式错误：verdict 必须为 pass 或 fail，请重试")
    if not isinstance(data.get("issues"), list):
        raise ReviewError("审稿问题清单格式错误，请重试")
    for issue in data["issues"]:
        if (
            not isinstance(issue, dict)
            or issue.get("severity") not in SEVERITIES
            or issue.get("dimension") not in DIMENSIONS
            or any(
                not isinstance(issue.get(key), str) for key in ("quote", "problem", "suggestion")
            )
        ):
            raise ReviewError("审稿问题条目格式错误，请重试")
    return {key: dimensions[key] for key in DIMENSIONS}


def _squash(text: str) -> str:
    """证据比对前的归一化：去掉空白、统一常见全半角差异。"""
    text = str(text or "")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    return re.sub(r"\s+", "", text)


def _verify_issues(body: str, items: Any) -> tuple[list[Issue], int]:
    haystack = _squash(body)
    issues: list[Issue] = []
    dropped = 0
    if not isinstance(items, list):
        return issues, dropped
    for raw in items[:24]:
        if not isinstance(raw, dict):
            dropped += 1
            continue
        severity = str(raw.get("severity") or "").strip().upper()
        if severity not in SEVERITIES:
            severity = "P1"
        quote = str(raw.get("quote") or "").strip()
        problem = str(raw.get("problem") or "").strip()
        if not quote or not problem:
            dropped += 1
            continue
        # 引用必须能在正文里逐字定位；对不上就说明是模型编的
        if _squash(quote) not in haystack:
            dropped += 1
            continue
        dimension = str(raw.get("dimension") or "").strip().lower()
        if dimension not in DIMENSION_LABELS:
            dimension = "structure"
        issues.append(
            Issue(
                severity=severity,
                dimension=dimension,
                quote=quote[:120],
                problem=problem[:300],
                suggestion=str(raw.get("suggestion") or "").strip()[:300],
            )
        )
    order = {name: index for index, name in enumerate(SEVERITIES)}
    issues.sort(key=lambda item: order.get(item.severity, 9))
    return issues, dropped


def run_review(
    project: Path,
    target: str,
    *,
    project_id: str = "",
    session_id: str = "",
    note: str = "",
    round_no: int | None = None,
) -> ReviewResult:
    """审一章，落盘并返回结果。"""
    chapter = load_chapter(project, target)
    body = str(chapter["body"]).strip()
    if len(_squash(body)) < 200:
        raise ReviewError("本章正文太短（不足 200 字），没有可审的内容")
    if len(body) > MAX_CHAPTER_CHARS:
        raise ReviewError(
            f"本章有 {len(body)} 字符，超过单章审稿上限 {MAX_CHAPTER_CHARS}；"
            "请分章后重试。本次没有调用模型，也不会用部分正文判定整章通过。"
        )

    text = body
    context = assemble_review(
        project,
        chapter_title=str(chapter["title"]),
        chapter_text=text,
        prev_tail=previous_tail(project, str(chapter["relative"])),
        note=note,
    )
    prompt = PROMPT.format(context=context.system_prompt)

    model = build_chat_model("reviewer")
    try:
        message = model.invoke(prompt, config={"tags": ["book:internal", "book:metered"]})
    except Exception as exc:  # noqa: BLE001 - 模型侧异常统一转成可读错误
        raise ReviewError(f"审稿模型调用失败：{type(exc).__name__}: {exc}") from exc

    parsed_usage = usage.parse_message(message)
    if project_id:
        usage.record(
            project_id=project_id,
            session_id=session_id,
            kind="review",
            model=parsed_usage["model"],
            input_tokens=parsed_usage["input"],
            output_tokens=parsed_usage["output"],
            cache_read=parsed_usage["cache_read"],
            calls=1,
        )

    content = getattr(message, "content", "")
    if isinstance(content, list):
        content = "".join(str(item) for item in content)
    data = _parse_json(str(content))

    dimensions = _validate_result(data)
    score = round(sum(dimensions.values()) / len(DIMENSIONS), 2)

    issues, dropped = _verify_issues(body, data.get("issues"))
    p0_count = len([item for item in issues if item.severity == "P0"])

    # verdict 由代码复核，不直接采信模型：有 P0 或均分不够就是 fail
    verdict = str(data.get("verdict") or "").strip().lower()
    passed = p0_count == 0 and score >= PASS_SCORE and verdict == "pass"
    status = "pass" if passed else "fail"

    previous_round = 0
    try:
        previous_round = int((chapter.get("review") or {}).get("round") or 0)
    except (TypeError, ValueError):
        previous_round = 0
    current_round = round_no if round_no is not None else previous_round + 1

    result = ReviewResult(
        status=status,
        score=score,
        dimensions=dimensions,
        issues=issues,
        summary=str(data.get("summary") or "").strip()[:600],
        verdict=verdict or status,
        model=parsed_usage["model"],
        reviewed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        round=max(1, current_round),
        dropped=dropped,
        chapter=str(chapter["relative"]),
        title=str(chapter["title"]),
        body_hash=body_hash(body),
        reviewed_chars=len(body),
    )
    save_review(project, chapter, result)
    return result


# ---------------------------------------------------------------- 落盘


def _review_file(project: Path, relative: str) -> Path:
    safe = relative.replace("\\", "/").replace("/", "__")
    if safe.endswith(".md"):
        safe = safe[:-3]
    return project / REVIEW_DIR / f"{safe}.json"


def save_review(project: Path, chapter: dict[str, Any], result: ReviewResult) -> None:
    """结论写 front-matter，明细写 .index/reviews。"""
    with project_lock(project):
        file = chapter["file"]
        current_meta, current_body = parse_note(read_text(file)) if file.exists() else ({}, "")
        detail = _review_file(project, str(chapter["relative"]))
        if not file.exists() or body_hash(current_body) != result.body_hash:
            # 结果属于旧稿：保留报告，但绝不把旧正文或旧元数据写回当前文件。
            result.status = "stale"
            history = detail.parent / "history" / detail.stem
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            save_text(
                history / f"{stamp}.json",
                json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            )
            if not detail.exists():
                save_text(detail, json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return

        meta = dict(current_meta)
        current_review = meta.get("review") if isinstance(meta.get("review"), dict) else {}
        try:
            previous_round = int(current_review.get("round") or 0)
        except (TypeError, ValueError):
            previous_round = 0
        result.round = max(result.round, previous_round + 1)
        meta["review"] = {
            "status": result.status,
            "round": result.round,
            "score": result.score,
            "model": result.model,
            "reviewed_at": result.reviewed_at,
            "body_hash": result.body_hash,
            "reviewed_chars": result.reviewed_chars,
        }
        write_project_text(project, file, dump_note(meta, current_body), invalidate=False)
        save_text(detail, json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        try:
            book = read_book_meta(project)
            chapters = dict(book.get("chapters") or {})
            chapters[str(chapter["relative"])] = dict(meta["review"])
            book["chapters"] = chapters
            write_book_meta(project, book)
        except (OSError, ValueError):
            pass


def _current_review(meta: dict[str, Any], body: str) -> dict[str, Any]:
    state = meta.get("review")
    if not isinstance(state, dict):
        return {}
    state = dict(state)
    if state.get("status") in {"pass", "fail"} and state.get("body_hash") != body_hash(body):
        # 外部编辑器也能改稿；旧版本的无摘要记录同样不能证明它审过当前正文。
        state["status"] = "stale"
    return state


def load_review(project: Path, target: str) -> dict[str, Any] | None:
    chapter = load_chapter(project, target)
    path = _review_file(project, str(chapter["relative"]))
    state = _current_review(chapter["meta"], chapter["body"])
    if path.exists():
        try:
            detail = json.loads(read_text(path))
            if isinstance(detail, dict):
                if not state or state.get("status") == "stale":
                    return {**detail, "status": "stale"}
                if detail.get("body_hash") == state.get("body_hash") and detail.get(
                    "round"
                ) == state.get("round"):
                    return {**detail, **state}
        except (json.JSONDecodeError, OSError):
            pass
    review = state
    if review:
        return {
            "chapter": chapter["relative"],
            "title": chapter["title"],
            "status": review.get("status"),
            "round": review.get("round"),
            "score": review.get("score"),
            "reviewed_at": review.get("reviewed_at"),
            "issues": [],
        }
    return None


def chapter_status(project: Path, target: str) -> str:
    review = load_review(project, target) or {}
    status = str(review.get("status") or "").strip()
    if status in {"pass", "fail", "stale"}:
        return status
    return "draft"


def list_reviews(project: Path) -> list[dict[str, Any]]:
    """章节列表 + 审稿状态，供前端文件树和审稿页使用。"""
    items: list[dict[str, Any]] = []
    for relative, file in chapter_files(project):
        meta, body = parse_note(read_text(file))
        review = _current_review(meta, body)
        if not review:
            detail = load_review(project, relative)
            if detail:
                review = detail
        status = str(review.get("status") or "draft")
        items.append(
            {
                "chapter": relative,
                "title": str(meta.get("title") or file.stem),
                "number": meta.get("chapter") or 0,
                "words": len(re.sub(r"\s+", "", body)),
                "status": status,
                "round": review.get("round") or 0,
                "score": review.get("score") or 0,
                "reviewed_at": review.get("reviewed_at") or "",
            }
        )
    return items


def review_model_name() -> str:
    settings = load_settings()
    return settings.reviewer.model or settings.active_model_id or "active"
