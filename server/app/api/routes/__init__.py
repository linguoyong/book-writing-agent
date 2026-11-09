"""API 路由聚合。

按域拆成多个模块，但共用 common.py 里的同一个 APIRouter，
所以这里的 import 顺序就是路由注册顺序——不要依赖 isort 的字母序，
`/projects/default-path` 必须先于 `/projects/{project_id}` 注册。

模块导入本身没有直接引用，是副作用导入（装饰器注册路由），
所以整个文件豁免 F401。
"""

# ruff: noqa: F401, I001

from __future__ import annotations

from . import (
    system,
    projects,
    sessions,
    kb,
    content,
    files,
    versions,
    review,
    deconstruct,
)
from .common import router

__all__ = ["router"]
