from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from ..config import McpServerSettings, load_settings

# 当前版本停用 MCP：工具在独立进程里执行，不经过本项目的路径沙箱与 diff 审批，
# 对「本地写作」这个场景收益有限、风险面却不小。代码保留，后续需要时打开。
MCP_ENABLED = False


def _fingerprint(servers: list[McpServerSettings]) -> str:
    return json.dumps(
        [
            {
                "name": s.name,
                "transport": s.transport,
                "command": s.command,
                "args": s.args,
                "env": s.env,
                "url": s.url,
                "enabled": s.enabled,
            }
            for s in servers
        ],
        ensure_ascii=False,
        sort_keys=True,
    )


def _connections(servers: list[McpServerSettings]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for server in servers:
        if not server.enabled:
            continue
        name = server.name.strip()
        if not name:
            continue
        if server.transport == "http":
            if server.url:
                result[name] = {"transport": "streamable_http", "url": server.url}
        elif server.command:
            conn: dict[str, Any] = {
                "transport": "stdio",
                "command": server.command,
                "args": server.args,
            }
            if server.env:
                conn["env"] = server.env
            result[name] = conn
    return result


class McpManager:
    """MCP 连接管理：按配置指纹缓存工具列表，配置变了才重连。

    有意做得保守：
    - 连接失败不抛错，只记录状态，对话照常（只是少一批工具）。
    - 工具名加服务器前缀（`<server>_<tool>`），避免和内置工具撞名。
    - MCP 工具在自己的进程里执行，不经过本项目的路径沙箱与 diff 审批，
      接入前需要用户在设置里显式启用。
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tools: list[Any] = []
        self._status: list[dict[str, Any]] = []
        self._fingerprint = ""

    async def refresh(self, *, force: bool = False) -> list[dict[str, Any]]:
        if not MCP_ENABLED:
            self._tools = []
            self._status = []
            return self._status
        async with self._lock:
            servers = load_settings().mcp
            fingerprint = _fingerprint(servers)
            if not force and fingerprint == self._fingerprint:
                return self._status
            self._fingerprint = fingerprint
            self._tools = []
            connections = _connections(servers)
            if not connections:
                self._status = [
                    {
                        "name": s.name,
                        "transport": s.transport,
                        "enabled": s.enabled,
                        "connected": False,
                        "tools": [],
                        "error": "" if s.enabled else "已停用",
                    }
                    for s in servers
                ]
                return self._status

            client = MultiServerMCPClient(connections, tool_name_prefix=True)
            status: list[dict[str, Any]] = []
            tools: list[Any] = []
            for name, conn in connections.items():
                try:
                    found = await client.get_tools(server_name=name)
                    tools.extend(found)
                    status.append(
                        {
                            "name": name,
                            "transport": conn["transport"],
                            "enabled": True,
                            "connected": True,
                            "tools": [tool.name for tool in found],
                            "error": "",
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    status.append(
                        {
                            "name": name,
                            "transport": conn["transport"],
                            "enabled": True,
                            "connected": False,
                            "tools": [],
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
            # 配置里已删除/停用的服务器不再出现在状态里
            known = {item["name"] for item in status}
            status.extend(
                {
                    "name": s.name,
                    "transport": s.transport,
                    "enabled": s.enabled,
                    "connected": False,
                    "tools": [],
                    "error": "已停用" if not s.enabled else "",
                }
                for s in servers
                if s.name not in known
            )
            self._tools = tools
            self._status = status
            return self._status

    async def get_tools(self) -> list[Any]:
        if not MCP_ENABLED:
            return []
        await self.refresh()
        return self._tools

    def snapshot(self) -> list[dict[str, Any]]:
        return self._status


manager = McpManager()
