from __future__ import annotations

import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import APP_HOME

AUTH_HEADER = "x-book-agent-token"
# 健康检查给 Electron 主进程轮询用，本身不返回任何业务数据
PUBLIC_PATHS = {"/api/health"}

_DISABLED = os.environ.get("BOOK_AGENT_DISABLE_AUTH", "").strip().lower() in {
    "1",
    "true",
    "yes",
}


def _load_token() -> str:
    """优先用宿主注入的令牌；手工启动时生成并落盘，方便 curl 自测。

    Electron 每次启动生成新令牌并通过 `BOOK_AGENT_TOKEN` 传给子进程；
    脱离桌面壳直接 `uvicorn` 时没有该变量，这里生成一个持久化令牌，
    避免「无令牌 = 不设防」。
    """
    env_token = os.environ.get("BOOK_AGENT_TOKEN", "").strip()
    if env_token:
        return env_token

    path = APP_HOME / "api.token"
    try:
        if path.exists():
            existing = path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        token = secrets.token_urlsafe(32)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token, encoding="utf-8")
        return token
    except OSError:
        # 磁盘不可写时退化为进程内令牌：仍然有鉴权，只是无法跨进程共享
        return secrets.token_urlsafe(32)


_TOKEN = "" if _DISABLED else _load_token()


def api_token() -> str:
    return _TOKEN


def auth_disabled() -> bool:
    return _DISABLED


class AuthMiddleware(BaseHTTPMiddleware):
    """所有 /api/* 都要带 `X-Book-Agent-Token`，OPTIONS 预检放行。

    服务只绑定 127.0.0.1，但浏览器里的任意网页同样能访问 loopback，
    仅靠 CORS 或绑定地址不构成边界，必须有令牌。
    """

    async def dispatch(self, request: Request, call_next):
        if _DISABLED:
            return await call_next(request)
        if request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        provided = request.headers.get(AUTH_HEADER, "")
        if not secrets.compare_digest(
            provided.encode("utf-8", "ignore"), _TOKEN.encode("utf-8")
        ):
            return JSONResponse(
                {"detail": "未授权：缺少或错误的访问令牌"}, status_code=401
            )
        return await call_next(request)
