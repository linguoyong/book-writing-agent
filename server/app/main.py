from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent.checkpointer import close_checkpointer, init_checkpointer
from .api.routes import router
from .config import load_settings
from .db import init_db
from .kb.updates import enable_updates
from .security import AuthMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    load_settings()
    await init_checkpointer()
    enable_updates(True)
    try:
        yield
    finally:
        enable_updates(False)
        await close_checkpointer()


app = FastAPI(title="Book Writing Agent", version="0.1.0", lifespan=lifespan)

# 先加鉴权，再加 CORS：后添加的中间件在更外层，401 响应也会带上 CORS 头。
app.add_middleware(AuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    # 服务只绑定 127.0.0.1，但 loopback 对浏览器是可达的：
    # 这里只放行桌面壳（file:// → Origin: null）与本地开发服务器，
    # 真正的边界是上面的令牌校验。
    allow_origins=["null"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
