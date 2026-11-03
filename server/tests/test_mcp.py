from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agent.mcp_manager import MCP_ENABLED, manager
from app.config import McpServerSettings


class McpDisabledTest(unittest.TestCase):
    """MCP 已停用：配置里就算有服务器，也不能起子进程或注入工具。"""

    def test_flag_is_off(self) -> None:
        self.assertFalse(MCP_ENABLED)

    def test_get_tools_is_empty_even_with_config(self) -> None:
        fake = SimpleNamespace(mcp=[McpServerSettings(name="x", command="calc.exe")])
        with patch("app.agent.mcp_manager.load_settings", return_value=fake):
            self.assertEqual(asyncio.run(manager.get_tools()), [])
            self.assertEqual(asyncio.run(manager.refresh(force=True)), [])


if __name__ == "__main__":
    unittest.main()
