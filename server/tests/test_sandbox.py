from __future__ import annotations

import unittest

from app.sandbox import (
    CommandRule,
    NetworkSettings,
    SandboxSettings,
    check_command,
    check_path,
    check_url,
    compile_permissions,
)


class PathRuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = SandboxSettings()

    def test_env_is_denied_anywhere(self) -> None:
        self.assertEqual(check_path(self.sandbox, ".env", "read"), "deny")
        self.assertEqual(check_path(self.sandbox, "kb/.env", "read"), "deny")
        self.assertEqual(check_path(self.sandbox, "manuscript/.env.local", "write"), "deny")

    def test_secrets_and_keys_denied(self) -> None:
        self.assertEqual(check_path(self.sandbox, "secrets/token.txt", "write"), "deny")
        self.assertEqual(check_path(self.sandbox, "kb/private.key", "read"), "deny")

    def test_git_config_write_denied(self) -> None:
        self.assertEqual(check_path(self.sandbox, ".git/config", "write"), "deny")

    def test_normal_path_falls_through_to_mode(self) -> None:
        # 未命中规则返回 allow，真正的兜底审批由 compile_permissions 的 /** 承担
        self.assertEqual(check_path(self.sandbox, "manuscript/a.md", "write"), "allow")


class CompilePermissionTest(unittest.TestCase):
    def test_ask_mode_appends_fallback_interrupt(self) -> None:
        permissions = compile_permissions(SandboxSettings(), mode="ask")
        self.assertTrue(
            any(item.mode == "interrupt" and item.paths == ["/**"] for item in permissions)
        )

    def test_auto_mode_has_no_fallback_but_keeps_deny(self) -> None:
        permissions = compile_permissions(SandboxSettings(), mode="auto")
        self.assertFalse(
            any(item.paths == ["/**"] and item.mode == "interrupt" for item in permissions)
        )
        self.assertTrue(any(item.mode == "deny" for item in permissions))


class CommandAndNetworkTest(unittest.TestCase):
    def test_command_defaults_to_deny(self) -> None:
        self.assertEqual(check_command(SandboxSettings(), "git status"), "deny")

    def test_command_allow_by_head(self) -> None:
        sandbox = SandboxSettings(commands=[CommandRule(pattern="git", mode="allow")])
        self.assertEqual(check_command(sandbox, "git status"), "allow")
        self.assertEqual(check_command(sandbox, "rm -rf /"), "deny")

    def test_url_defaults_to_deny(self) -> None:
        self.assertEqual(check_url(SandboxSettings(), "https://example.com"), "deny")

    def test_url_allow_suffix_only(self) -> None:
        sandbox = SandboxSettings(network=NetworkSettings(allow=["api.deepseek.com"]))
        self.assertEqual(check_url(sandbox, "https://api.deepseek.com/v1"), "allow")
        self.assertEqual(check_url(sandbox, "https://api.deepseek.com.evil.com/x"), "deny")

    def test_url_userinfo_cannot_fake_host(self) -> None:
        # https://allowed:443@evil.com/ 的真实主机是 evil.com，
        # 按 ":" 切字符串会误判成 allowed.com
        sandbox = SandboxSettings(network=NetworkSettings(allow=["allowed.com"]))
        self.assertEqual(check_url(sandbox, "https://allowed.com:443@evil.com/x"), "deny")
        self.assertEqual(check_url(sandbox, "https://user:pw@allowed.com/x"), "allow")

    def test_url_ignores_port_and_trailing_dot(self) -> None:
        sandbox = SandboxSettings(network=NetworkSettings(allow=["example.com"]))
        self.assertEqual(check_url(sandbox, "http://example.com:8080/a"), "allow")
        self.assertEqual(check_url(sandbox, "https://example.com./a"), "allow")

    def test_url_garbage_is_denied(self) -> None:
        sandbox = SandboxSettings(network=NetworkSettings(default="allow"))
        self.assertEqual(check_url(sandbox, "http://[::1"), "deny")
        self.assertEqual(check_url(SandboxSettings(), ""), "deny")


if __name__ == "__main__":
    unittest.main()
