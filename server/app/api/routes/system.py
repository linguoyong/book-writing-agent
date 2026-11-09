"""健康检查、配置、向量服务、MCP、沙箱与域列表。"""

from __future__ import annotations

from .common import (
    DEFAULT_LOCAL_MODEL,
    LOCAL_MODELS,
    MASKED_KEY,
    MCP_ENABLED,
    Any,
    EmbeddingTestRequest,
    PricingRequest,
    SandboxCheckRequest,
    _mask_secrets,
    check_command,
    check_url,
    list_domains,
    load_settings,
    mcp_manager,
    normalize_window,
    probe_embedding,
    router,
    save_pricing,
    save_settings,
)

# ---------------------------------------------------------------- 配置


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/config")
def get_config() -> dict[str, Any]:
    return _mask_secrets(load_settings().model_dump())


@router.put("/config")
def put_config(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    merged = settings.model_dump()
    before_embedding = dict(merged.get("embedding") or {})
    for key in ("writer", "extractor", "embedding", "sandbox"):
        if key in payload and isinstance(payload[key], dict):
            patch = dict(payload[key])
            if patch.get("api_key") == MASKED_KEY:
                patch.pop("api_key", None)
            merged[key].update(patch)
    if isinstance(payload.get("mcp"), list):
        # 回显过的 env 是 ***，按服务器名把原值换回来，避免把掩码写进配置
        previous_mcp = {
            str(item.get("name")): item
            for item in (merged.get("mcp") or [])
            if isinstance(item, dict)
        }
        servers: list[dict[str, Any]] = []
        for item in payload["mcp"]:
            if not isinstance(item, dict):
                continue
            env = item.get("env")
            if isinstance(env, dict):
                previous_env = (previous_mcp.get(str(item.get("name"))) or {}).get("env") or {}
                item["env"] = {
                    str(key): (previous_env.get(key, value) if value == MASKED_KEY else value)
                    for key, value in env.items()
                }
            servers.append(item)
        merged["mcp"] = servers
    if isinstance(payload.get("models"), list):
        previous = {
            str(item.get("id")): item
            for item in (merged.get("models") or [])
            if isinstance(item, dict)
        }
        models: list[dict[str, Any]] = []
        for item in payload["models"]:
            if not isinstance(item, dict):
                continue
            patch = dict(item)
            if patch.get("api_key") == MASKED_KEY:
                # 前端拿到的是 ***：按 id 回填原密钥，避免把占位符写进配置
                patch["api_key"] = previous.get(str(patch.get("id")), {}).get("api_key", "")
            models.append(patch)
        merged["models"] = models
    if isinstance(payload.get("active_model_id"), str):
        merged["active_model_id"] = payload["active_model_id"]
    for role in ("writer", "extractor"):
        if merged.get(role, {}).get("context_window"):
            merged[role]["context_window"] = normalize_window(merged[role]["context_window"])
    save_settings(type(settings).model_validate(merged))
    saved = load_settings()
    after_embedding = saved.embedding
    changed = any(
        before_embedding.get(key) != getattr(after_embedding, key)
        for key in ("provider", "local_model", "model", "base_url")
    )
    result = _mask_secrets(saved.model_dump())
    # 前端的 AppConfig 不认识这个字段也没关系：只是用来提示「需要重建索引」
    result["embedding_changed"] = changed
    return result


@router.get("/embeddings/options")
def embedding_options() -> dict[str, Any]:
    return {
        "default": DEFAULT_LOCAL_MODEL,
        "local": [{"id": key, **value} for key, value in LOCAL_MODELS.items()],
    }


@router.post("/embeddings/test")
def test_embedding(req: EmbeddingTestRequest) -> dict[str, Any]:
    """真跑一次编码：本地模型首次会下载/加载，可能要几十秒。"""
    cfg = load_settings().embedding.model_copy(deep=True)
    cfg.provider = req.provider or cfg.provider
    if req.base_url:
        cfg.base_url = req.base_url
    if req.model:
        cfg.model = req.model
    if req.local_model:
        cfg.local_model = req.local_model
    if req.api_key and req.api_key != MASKED_KEY:
        cfg.api_key = req.api_key
    return probe_embedding(cfg)


@router.get("/usage/pricing")
def get_usage_pricing() -> dict[str, Any]:
    settings = load_settings()
    return {
        "pricing": {name: price.model_dump() for name, price in (settings.pricing or {}).items()},
        "currency": "CNY",
        "unit": "元 / 百万 token",
    }


@router.put("/usage/pricing")
def put_usage_pricing(req: PricingRequest) -> dict[str, Any]:
    return {"pricing": save_pricing(req.pricing), "currency": "CNY"}


@router.get("/mcp/status")
async def mcp_status() -> dict[str, Any]:
    status = await mcp_manager.refresh()
    return {"enabled": MCP_ENABLED, "servers": status}


@router.post("/mcp/reload")
async def mcp_reload() -> dict[str, Any]:
    status = await mcp_manager.refresh(force=True)
    return {"enabled": MCP_ENABLED, "servers": status}


@router.post("/sandbox/check")
def sandbox_check(req: SandboxCheckRequest) -> dict[str, Any]:
    settings = load_settings()
    fn = check_command if req.kind == "command" else check_url
    return {"result": fn(settings.sandbox, req.value)}


# ---------------------------------------------------------------- 内核：域包与记忆


@router.get("/domains")
def get_domains() -> list[dict[str, str]]:
    return list_domains()
