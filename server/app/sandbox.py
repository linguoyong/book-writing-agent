from __future__ import annotations

from typing import Literal

from deepagents import FilesystemPermission
from pydantic import BaseModel, Field, field_validator

Mode = Literal["allow", "ask", "deny"]

_RANK = {"allow": 0, "ask": 1, "deny": 2}
_MODE_MAP = {"allow": "allow", "ask": "interrupt", "deny": "deny"}


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


def compile_permissions(
    sandbox: SandboxSettings | None, *, write_policy: Literal["ask", "allow"] = "ask"
) -> list[FilesystemPermission]:
    """把规则表编译成 deepagents 的权限栈；先匹配先生效。

    注意：deepagents 只有 read / write 两类操作，delete 归入 write，
    因此一条规则的 write 与 delete 取更严格者。
    """
    permissions: list[FilesystemPermission] = []
    for rule in (sandbox.rules if sandbox else []):
        patterns = _expand(rule.pattern)
        if not patterns:
            continue
        if rule.read != "allow":
            permissions.append(
                FilesystemPermission(
                    operations=["read"], paths=patterns, mode=_MODE_MAP[rule.read]
                )
            )
        write_mode = _strongest(rule.write, rule.delete)
        if write_mode != "allow":
            permissions.append(
                FilesystemPermission(
                    operations=["write"], paths=patterns, mode=_MODE_MAP[write_mode]
                )
            )

    if write_policy == "ask":
        # 兜底：所有写入都要人工确认（规则表里更严格的 deny 在前面先命中）
        permissions.append(
            FilesystemPermission(operations=["write"], paths=["/**"], mode="interrupt")
        )
    return permissions
