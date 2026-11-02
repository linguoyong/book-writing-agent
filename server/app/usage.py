from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .config import ModelPrice, load_settings, save_settings
from .db import get_conn, now_iso, session_titles

# 用量分类：对话轮次 / 逐章抽取 / 选中改写
KINDS = ("chat", "extract", "rewrite")
MAX_DAYS = 180


def parse_message(output: Any) -> dict[str, Any]:
    """从一条 AIMessage / AIMessageChunk 里取出 token 用量。"""
    usage = getattr(output, "usage_metadata", None) or {}
    meta = getattr(output, "response_metadata", None) or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    details = usage.get("input_token_details") or {}
    cache_read = int(details.get("cache_read") or 0)
    if not input_tokens and not output_tokens:
        # 兜底：部分 provider 只填 response_metadata.token_usage
        raw = meta.get("token_usage") or meta.get("usage") or {}
        input_tokens = int(raw.get("prompt_tokens") or raw.get("input_tokens") or 0)
        output_tokens = int(
            raw.get("completion_tokens") or raw.get("output_tokens") or 0
        )
        cache_read = int(
            raw.get("prompt_cache_hit_tokens")
            or (raw.get("prompt_tokens_details") or {}).get("cached_tokens")
            or cache_read
        )
    name = meta.get("model_name") or meta.get("model") or ""
    return {
        "model": str(name),
        "input": input_tokens,
        "output": output_tokens,
        "cache_read": cache_read,
        "reported": bool(input_tokens or output_tokens),
    }


class UsageMeter:
    """按次累加一轮对话的 token，最后一次性落库。

    取自 `on_chat_model_end` 事件：主模型与子代理（task）的调用都会出现，
    两者都真花钱，不区分是否子代理。上游没回 usage 的（部分兼容端点流式不返
    `usage`）计入 `calls` 但没有 token 数，界面会显示「未回报用量」。
    """

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read = 0
        self.calls = 0
        self.reported = 0
        self.model = ""
        self.flushed = False

    def add(self, output: Any) -> None:
        parsed = parse_message(output)
        self.calls += 1
        if parsed["reported"]:
            self.reported += 1
        self.input_tokens += parsed["input"]
        self.output_tokens += parsed["output"]
        self.cache_read += parsed["cache_read"]
        if parsed["model"]:
            self.model = parsed["model"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "input": self.input_tokens,
            "output": self.output_tokens,
            "total": self.input_tokens + self.output_tokens,
            "cache_read": self.cache_read,
            "calls": self.calls,
            "reported": self.reported,
            "model": self.model,
        }

    def flush(
        self,
        *,
        project_id: str,
        session_id: str = "",
        kind: str = "chat",
        elapsed_ms: int = 0,
    ) -> dict[str, Any] | None:
        if self.flushed:
            return None
        self.flushed = True
        if not self.calls:
            return None
        return record(
            project_id=project_id,
            session_id=session_id,
            kind=kind,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read=self.cache_read,
            calls=self.calls,
            elapsed_ms=elapsed_ms,
        )


def record(
    *,
    project_id: str,
    session_id: str = "",
    kind: str = "chat",
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read: int = 0,
    calls: int = 0,
    elapsed_ms: int = 0,
) -> dict[str, Any] | None:
    """写一条用量记录。没有任何 token 也没有调用次数时直接跳过。"""
    if not project_id:
        return None
    if not calls and not (input_tokens or output_tokens):
        return None
    kind = kind if kind in KINDS else "chat"
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO usage_log (project_id, session_id, kind, model, input_tokens, "
            "output_tokens, cache_read, calls, elapsed_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                session_id,
                kind,
                model,
                max(0, int(input_tokens)),
                max(0, int(output_tokens)),
                max(0, int(cache_read)),
                max(0, int(calls)),
                max(0, int(elapsed_ms)),
                now_iso(),
            ),
        )
    return {
        "kind": kind,
        "model": model,
        "input": int(input_tokens),
        "output": int(output_tokens),
        "total": int(input_tokens) + int(output_tokens),
        "cache_read": int(cache_read),
        "calls": int(calls),
    }


def _local_date(value: str) -> str:
    """把 UTC 时间戳折成本地日期，聚合按用户看到的「今天」算。"""
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return str(value)[:10]
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().date().isoformat()


def _price_of(pricing: dict[str, ModelPrice], model: str) -> ModelPrice | None:
    if not pricing:
        return None
    if model in pricing:
        price = pricing[model]
        return price if (price.input or price.output or price.cache_read) else None
    return None


def _cost(
    input_tokens: int, output_tokens: int, cache_read: int, price: ModelPrice | None
) -> float:
    if not price:
        return 0.0
    # cache_read 是输入里的命中部分，不能整份再算一遍，否则重复计价
    cached = min(max(0, cache_read), max(0, input_tokens))
    uncached = max(0, input_tokens - cached)
    cache_price = price.cache_read or price.input
    total = (
        uncached / 1_000_000 * price.input
        + cached / 1_000_000 * cache_price
        + output_tokens / 1_000_000 * price.output
    )
    return round(total, 4)


def _empty_bucket() -> dict[str, int]:
    return {
        "input": 0,
        "output": 0,
        "total": 0,
        "cache_read": 0,
        "calls": 0,
        "turns": 0,
    }


def _accumulate(bucket: dict[str, int], row: dict[str, Any]) -> None:
    bucket["input"] += int(row["input_tokens"] or 0)
    bucket["output"] += int(row["output_tokens"] or 0)
    bucket["total"] += int(row["input_tokens"] or 0) + int(row["output_tokens"] or 0)
    bucket["cache_read"] += int(row["cache_read"] or 0)
    bucket["calls"] += int(row["calls"] or 0)
    bucket["turns"] += 1


def summary(project_id: str, days: int = 14) -> dict[str, Any]:
    """按天 / 模型 / 会话聚合最近 N 天用量，并按设置的单价折算成本。"""
    days = max(1, min(int(days or 14), MAX_DAYS))
    settings = load_settings()
    pricing = settings.pricing or {}

    today = datetime.now().astimezone().date()
    start = today - timedelta(days=days - 1)
    with get_conn() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM usage_log WHERE project_id = ? ORDER BY id DESC",
                (project_id,),
            )
        ]

    totals = _empty_bucket()
    today_bucket = _empty_bucket()
    buckets: dict[str, dict[str, int]] = {
        (start + timedelta(days=offset)).isoformat(): _empty_bucket()
        for offset in range(days)
    }
    by_model: dict[str, dict[str, Any]] = {}
    by_session: dict[str, dict[str, Any]] = {}
    by_kind: dict[str, dict[str, int]] = {}
    cost_total = 0.0
    cost_today = 0.0
    priced_models: set[str] = set()

    cost_by_day: dict[str, float] = {day: 0.0 for day in buckets}

    for row in rows:
        day = _local_date(row["created_at"])
        model = row["model"] or "未回报"
        price = _price_of(pricing, row["model"] or "")
        cost = _cost(
            int(row["input_tokens"] or 0),
            int(row["output_tokens"] or 0),
            int(row["cache_read"] or 0),
            price,
        )
        if price:
            priced_models.add(row["model"])
        if day == today.isoformat():
            cost_today += cost
            _accumulate(today_bucket, row)
        if day not in buckets:
            continue
        cost_total += cost
        cost_by_day[day] = round(cost_by_day[day] + cost, 4)
        _accumulate(totals, row)
        _accumulate(buckets[day], row)
        target = by_model.setdefault(
            model, {**_empty_bucket(), "model": model, "cost": 0.0}
        )
        _accumulate(target, row)
        target["cost"] = round(target["cost"] + cost, 4)
        if row["kind"] == "chat" and row["session_id"]:
            key = row["session_id"]
            entry = by_session.setdefault(
                key,
                {
                    **_empty_bucket(),
                    "session_id": key,
                    "cost": 0.0,
                    "last_at": row["created_at"],
                },
            )
            _accumulate(entry, row)
            entry["cost"] = round(entry["cost"] + cost, 4)
            if str(row["created_at"]) > str(entry["last_at"]):
                entry["last_at"] = row["created_at"]
        kind_entry = by_kind.setdefault(row["kind"], _empty_bucket())
        _accumulate(kind_entry, row)

    titles = session_titles(list(by_session))
    sessions = []
    for entry in by_session.values():
        entry["title"] = titles.get(entry["session_id"], "(已删除的会话)")
        sessions.append(entry)
    sessions.sort(key=lambda item: item["total"], reverse=True)

    series = [
        {
            "date": day,
            "input": bucket["input"],
            "output": bucket["output"],
            "total": bucket["total"],
            "cost": cost_by_day.get(day, 0.0),
        }
        for day, bucket in buckets.items()
    ]

    models = sorted(by_model.values(), key=lambda item: item["total"], reverse=True)
    return {
        "days": days,
        "since": start.isoformat(),
        "totals": totals,
        "today": today_bucket,
        "series": series,
        "by_model": models,
        "by_session": sessions[:20],
        "by_kind": [
            {"kind": kind, **bucket} for kind, bucket in sorted(by_kind.items())
        ],
        "pricing": {
            name: price.model_dump() for name, price in (settings.pricing or {}).items()
        },
        "priced_models": sorted(priced_models),
        "cost": {
            "total": round(cost_total, 4),
            "today": round(cost_today, 4),
            "currency": "CNY",
            "has_pricing": bool(priced_models),
        },
        "recorded": len(rows),
    }


def set_pricing(prices: dict[str, dict[str, float]]) -> dict[str, Any]:
    """保存模型单价。传空对象即清空；单价非负数，单位元/百万 token。"""
    cleaned: dict[str, ModelPrice] = {}
    for name, value in (prices or {}).items():
        key = str(name).strip()
        if not key or not isinstance(value, dict):
            continue
        cleaned[key] = ModelPrice(
            input=max(0.0, float(value.get("input") or 0)),
            output=max(0.0, float(value.get("output") or 0)),
            cache_read=max(0.0, float(value.get("cache_read") or 0)),
        )
    settings = load_settings()
    settings.pricing = cleaned
    save_settings(settings)
    return {name: price.model_dump() for name, price in cleaned.items()}
