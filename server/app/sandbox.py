from __future__ import annotations

from typing import Literal

from deepagents import FilesystemPermission
from pydantic import BaseModel, Field, field_validator
from wcmatch import glob as wcglob

Mode = Literal["allow", "ask", "deny"]
PermissionMode = Literal["ask", "auto"]

_RANK = {"allow": 0, "ask": 1, "deny": 2}
_MODE_MAP = {"allow": "allow", "ask": "interrupt", "deny": "deny"}
_GLOB_FLAGS = wcglob.BRACE | wcglob.GLOBSTAR


class PathRule(BaseModel):
    """工作区内的路径规则。pattern 支持 glob：`secrets/**`、`**/*.key`、`.env`。"""

    pattern: str
    read: Mode = "allow"
    write: Mode = "ask"
    delete: Mode = "deny"
    note: str = ""

    @field_validator("pattern")
    @classmethod
    def _clean(cls, value: str) -> str:
        value = value.strip().replace("\\", "/")
        if not value:
            raise ValueError("路径不能为空")
        if ".." in value.split("/") or value.startswith("~"):
            raise ValueError("规则只支持工作区内相对路径，不支持 .. 或 ~")
        return value


DEFAULT_RULES: list[dict[str, str]] = [
    {"pattern": ".env", "read": "deny", "write": "deny", "delete": "deny", "note": "环境变量常含密钥"},
    {"pattern": ".env.*", "read": "deny", "write": "deny", "delete": "deny", "note": "环境变量变体"},
    {"pattern": "secrets/**", "read": "deny", "write": "deny", "delete": "deny", "note": "凭据目录"},
    {"pattern": "*.pem", "read": "deny", "write": "deny", "delete": "deny", "note": "私钥"},
    {"pattern": "*.key", "read": "deny", "write": "deny", "delete": "deny", "note": "私钥"},
    {"pattern": "id_rsa*", "read": "deny", "write": "deny", "delete": "deny", "note": "SSH 私钥"},
    {"pattern": ".git/config", "read": "allow", "write": "deny", "delete": "deny", "note": "防止改写远端地址"},
]


class SandboxSettings(BaseModel):
    default_mode: PermissionMode = "ask"
    rules: list[PathRule] = Field(
        default_factory=lambda: [PathRule(**rule) for rule in DEFAULT_RULES]
    )


def _expand(pattern: str) -> list[str]:
    raw = pattern.strip().lstrip("/")
    if not raw:
        return []
    if "/" in raw or raw.startswith("**"):
        return [f"/{raw}"]
    # 裸文件名：匹配根目录与任意深度，避免漏掉嵌套的 .env / 私钥
    return [f"/{raw}", f"/**/{raw}"]


def _strongest(*modes: str) -> str:
    return max(modes, key=lambda mode: _RANK.get(mode, 0))


def _mapped(mode: str, ask_mode: str) -> str:
    return ask_mode if mode == "ask" else _MODE_MAP[mode]


def compile_permissions(
    sandbox: SandboxSettings | None, *, mode: PermissionMode = "ask"
) -> list[FilesystemPermission]:
    """把规则表编译成 deepagents 的权限栈；先匹配先生效。

    - ask：规则里的 ask 一律中断审批，末尾再加 `/**` 写入兜底审批。
    - auto（完全访问）：规则里的 ask 直接放行，不再有兜底审批；deny 仍然生效。
    """
    ask_mode = "interrupt" if mode == "ask" else "allow"
    permissions: list[FilesystemPermission] = []
    for rule in (sandbox.rules if sandbox else []):
        patterns = _expand(rule.pattern)
        if not patterns:
            continue
        read_target = _mapped(rule.read, ask_mode)
        if read_target != "allow":
            permissions.append(
                FilesystemPermission(
                    operations=["read"], paths=patterns, mode=read_target
                )
            )
        write_target = _mapped(_strongest(rule.write, rule.delete), ask_mode)
        if write_target != "allow":
            permissions.append(
                FilesystemPermission(
                    operations=["write"], paths=patterns, mode=write_target
                )
            )

    if mode == "ask":
        # 兜底：所有写入都要人工确认（规则表里更严格的 deny 在前面先命中）
        permissions.append(
            FilesystemPermission(operations=["write"], paths=["/**"], mode="interrupt")
        )
    return permissions


def check_path(
    sandbox: SandboxSettings | None, path: str, operation: Literal["read", "write"] = "write"
) -> str:
    """给自研工具用的规则查询：返回 allow / ask / deny。"""
    if sandbox is None:
        return "allow"
    normalized = "/" + path.replace("\\", "/").lstrip("/")
    for rule in sandbox.rules:
        if any(
            wcglob.globmatch(normalized, pattern, flags=_GLOB_FLAGS)
            for pattern in _expand(rule.pattern)
        ):
            return rule.read if operation == "read" else _strongest(rule.write, rule.delete)
    return "allow"
