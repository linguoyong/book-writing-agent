"""冻结后的后端入口：PyInstaller 打出的 exe 直接跑这个。

Electron 拉起后端时有两种形态：
- 开发态：`python -m uvicorn app.main:app`
- 安装包：`resources/server-bin/book-server.exe`（本文件冻结产物）

端口与令牌都由主进程通过环境变量给出，和开发态保持一致。
"""

from __future__ import annotations

import multiprocessing
import os
import sys


def main() -> int:
    host = os.environ.get("BOOK_AGENT_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("BOOK_AGENT_PORT", "8787"))
    except ValueError:
        port = 8787

    # uvicorn 的 import 放在函数里：冻结时 PyInstaller 仍能静态分析到，
    # 但单独 import 这个文件做语法检查时不会拉起一堆依赖。
    import uvicorn

    from app.main import app

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.environ.get("BOOK_AGENT_LOG_LEVEL", "info"),
        access_log=False,
        # 安装包形态不需要 reload / workers，单进程足够
        workers=None,
    )
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
