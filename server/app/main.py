from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent.checkpointer import close_checkpointer, init_checkpointer
from .api.routes import router
from .config import load_settings
from .db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    load_settings()
    await init_checkpointer()
    try:
        yield
    finally:
        await close_checkpointer()


app = FastAPI(title="Book Writing Agent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # 服务只绑定 127.0.0.1；Electron 以 file:// 加载页面，Origin 为 null，
    # 因此这里放开来源，靠 loopback 绑定与本地权限规则做边界。
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
