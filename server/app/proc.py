"""子进程调用：Windows 下必须顺手关掉控制台窗口。

冻结后的后端是 windowed 程序（PE subsystem=2，见 book-server.spec 的 console=False），
它拉起 git 这类控制台程序时，不显式传 CREATE_NO_WINDOW 就会**新开一个黑框**。
一次写入要跑好几次 git（status / diff / numstat / commit），用户看到的就是
「一堆窗口一闪而过」。开发态跑在 python.exe 里没这问题——子进程继承了父进程的控制台，
所以这个坑只在安装包里出现。
"""

from __future__ import annotations

import subprocess
from typing import Any

# 非 Windows 上取不到这个常量，退化成 0（等价于不传）
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_hidden(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    """等同于 subprocess.run，但不弹控制台窗口。

    调用方传了 creationflags 就尊重调用方（虽然目前没有这种调用）。
    """
    if "creationflags" not in kwargs:
        kwargs["creationflags"] = _NO_WINDOW
    return subprocess.run(args, **kwargs)
