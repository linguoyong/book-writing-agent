from __future__ import annotations

import asyncio
import ssl
import time
from contextlib import aclosing
from functools import lru_cache
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
import openai
from pydantic import BaseModel

from .config import ModelProfile, ModelSettings, Settings, resolve_model
from .llm import chat_model_from_settings

PROBE_TIMEOUT = 30


@lru_cache(maxsize=1)
def _tls_context() -> ssl.SSLContext:
    # 多个并发测试共享证书上下文，避免 Windows 每次构造连接池时重复加载证书。
    return httpx.create_ssl_context()


class ModelTestRequest(BaseModel):
    role: Literal["writer", "extractor", "reviewer"]
    settings: ModelSettings
    model_id: str = ""
    fallback_model: ModelProfile | None = None


async def probe_model(req: ModelTestRequest, saved: Settings) -> dict[str, Any]:
    """测试当前草稿的真实流式调用，不保存配置或写入任何会话。"""
    started = time.perf_counter()
    source: ModelSettings | ModelProfile = req.settings.model_copy(deep=True)
    previous: ModelSettings | ModelProfile | None
    if req.role == "reviewer" and not source.model.strip():
        source = (req.fallback_model or resolve_model(saved)).model_copy(deep=True)
        previous = next((item for item in saved.models if item.id == source.id), None)
    elif req.role == "writer":
        previous = next((item for item in saved.models if item.id == req.model_id), None)
    else:
        previous = getattr(saved, req.role)

    def result(error: str = "") -> dict[str, Any]:
        return {
            "ok": not error,
            "error": error,
            "model": source.model,
            "ms": round((time.perf_counter() - started) * 1000),
        }

    if source.api_key == "***":
        if previous is None or not previous.api_key:
            return result("找不到已保存的 API Key，请输入密钥后再测试。")
        source.api_key = previous.api_key
    source.base_url = source.base_url.strip()
    source.model = source.model.strip()
    if not source.model:
        return result("请先填写模型名。")
    try:
        url = urlsplit(source.base_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            return result("请填写有效的 Base URL（以 http:// 或 https:// 开头）。")
        _ = url.port
    except ValueError:
        return result("Base URL 格式不正确，请检查地址和端口。")

    try:
        # 使用独立连接池，关闭测试请求不会影响正常对话复用的客户端。
        async with asyncio.timeout(PROBE_TIMEOUT):
            tls = await asyncio.to_thread(_tls_context)
            with httpx.Client(verify=tls) as sync_client:
                async with httpx.AsyncClient(verify=tls) as async_client:
                    model = chat_model_from_settings(
                        source,
                        timeout=PROBE_TIMEOUT,
                        max_retries=0,
                        http_client=sync_client,
                        http_async_client=async_client,
                    )
                    async with aclosing(model.astream("请只回复 OK。")) as stream:
                        async for chunk in stream:
                            if chunk.content or chunk.additional_kwargs.get("reasoning_content"):
                                return result()
        return result("服务已连接，但模型没有返回内容，请检查模型名和服务配置。")
    except (TimeoutError, openai.APITimeoutError):
        return result(f"连接超时（{PROBE_TIMEOUT} 秒），请检查网络、服务地址或稍后重试。")
    except openai.AuthenticationError:
        return result("认证失败，请检查 API Key 是否正确、是否已过期。")
    except openai.PermissionDeniedError:
        return result("没有访问权限，请检查 API Key 是否有权使用此模型。")
    except openai.NotFoundError:
        return result("找不到接口或模型，请检查 Base URL 和模型名。")
    except openai.RateLimitError:
        return result("服务额度不足或请求过于频繁，请检查余额或稍后重试。")
    except openai.APIConnectionError:
        return result("无法连接模型服务，请检查 Base URL、网络和代理设置。")
    except openai.APIStatusError as exc:
        # 不回显服务商原始错误：其中可能包含请求正文或密钥。
        return result(
            f"服务拒绝请求（HTTP {exc.status_code}），请检查模型名、Temperature 和推理强度等设置。"
        )
    except ValueError:
        return result("模型未返回有效内容，请检查模型名和服务配置。")
    except Exception:
        return result("模型测试失败，请检查服务配置或稍后重试。")
