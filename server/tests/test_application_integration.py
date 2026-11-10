"""Cross-module acceptance tests over HTTP against an isolated application process."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import httpx

from tests.application_testbed import BODY, TOKEN


class ApplicationIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(
            prefix="book-http-tests-", ignore_cleanup_errors=True
        )
        cls.home = Path(cls.temp.name)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{port}/api"
        cls.log = (cls.home / "server.log").open("w", encoding="utf-8")
        cls.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.application_testbed",
                "--port",
                str(port),
                "--home",
                str(cls.home),
            ],
            cwd=Path(__file__).resolve().parents[1],
            stdout=cls.log,
            stderr=cls.log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        cls.client = httpx.Client(
            base_url=cls.base, headers={"X-Book-Agent-Token": TOKEN}, timeout=25
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if cls.client.get("/health").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        cls.process.terminate()
        cls.process.wait(timeout=10)
        cls.log.close()
        raise RuntimeError((cls.home / "server.log").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.process.terminate()
        cls.process.wait(timeout=10)
        cls.log.close()
        cls.temp.cleanup()

    def request(self, method, path, body=None, status=200, **kwargs):
        response = self.client.request(method, path, json=body, **kwargs)
        self.assertEqual(response.status_code, status, f"{method} {path}: {response.text[:1500]}")
        return response.json()

    def setUp(self):
        self.project = self.request("POST", "/projects", {"name": self.id().split(".")[-1]})
        self.pid = self.project["id"]
        self.root = Path(self.project["path"])
        self.url = f"/projects/{self.pid}"

    def session(self, **options):
        return self.request("POST", self.url + "/sessions", {"title": "测试会话", **options})["id"]

    def events(self, response):
        self.assertEqual(response.status_code, 200, response.text[:1000])
        result = []
        for block in response.text.split("\n\n"):
            kind = next((line[7:] for line in block.splitlines() if line.startswith("event: ")), "")
            data = next(
                (line[6:] for line in block.splitlines() if line.startswith("data: ")), "null"
            )
            if kind:
                result.append((kind, json.loads(data)))
        return result

    def chat(self, sid, message, mode="main"):
        return self.events(
            self.client.post("/chat", json={"session_id": sid, "message": message, "mode": mode})
        )

    def tool(self, sid, name, args, mode="main"):
        return self.chat(
            sid, "TEST_TOOL " + json.dumps({"name": name, "args": args}, ensure_ascii=False), mode
        )

    def test_permission_switch_resumes_all_outline_stages(self):
        sid = self.session(permission_mode="ask")
        events = self.chat(sid, "TEST_OUTLINE 先写大纲")
        self.assertIn("approval", [kind for kind, _ in events])
        first = next(data for kind, data in events if kind == "done")
        time.sleep(1.1)  # 审批等待也属于这一轮，不能被最后一段的短计时覆盖。
        self.request("PATCH", f"/sessions/{sid}", {"permission_mode": "auto"})
        events = self.events(
            self.client.post(
                "/chat/approve",
                json={
                    "session_id": sid,
                    "decisions": [{"type": "approve"}],
                },
            )
        )
        self.assertNotIn("error", [kind for kind, _ in events], str(events))
        for name in ("main", "vol-01"):
            path = self.root / "kb" / "outline" / f"{name}.md"
            self.assertTrue(path.exists(), str(events))
            self.assertGreater(path.stat().st_size, 30)
        self.assertIn(
            "已完成总纲和第一卷大纲",
            "".join(data.get("text", "") for kind, data in events if kind == "token"),
        )
        self.assertIsNone(self.request("GET", f"/sessions/{sid}/pending")["approval"])
        final = next(data for kind, data in events if kind == "done")
        self.assertGreaterEqual(final["elapsed_ms"], first["elapsed_ms"] + 1100)
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["started_at"], first["started_at"])
        overview = self.request("GET", self.url + "/overview")
        self.assertEqual(overview["kb_counts"]["outline"], 2)
        self.assertEqual(overview["kb_counts"]["world"], 1)
        messages = self.request("GET", f"/sessions/{sid}/messages")
        self.assertIn("已完成总纲", messages[-1]["content"])
        self.assertEqual(messages[-1]["meta"]["turn"]["phase_id"], final["phase_id"])

    def test_auto_mode_completes_multi_stage_outline(self):
        sid = self.session(permission_mode="auto")
        events = self.chat(sid, "TEST_OUTLINE 先写大纲")
        self.assertNotIn("approval", [kind for kind, _ in events], str(events))
        self.assertTrue((self.root / "kb/outline/main.md").exists(), str(events))
        self.assertTrue((self.root / "kb/outline/vol-01.md").exists(), str(events))

    def test_manual_approvals_keep_later_stages_paused_until_approved(self):
        sid = self.session(permission_mode="ask")
        self.chat(sid, "TEST_OUTLINE 先写大纲")
        for stage in range(3):
            self.assertIsNotNone(self.request("GET", f"/sessions/{sid}/pending")["approval"])
            events = self.events(
                self.client.post(
                    "/chat/approve",
                    json={
                        "session_id": sid,
                        "decisions": [{"type": "approve"}],
                    },
                )
            )
            self.assertNotIn("error", [kind for kind, _ in events], str(events))
            if stage < 2:
                self.assertEqual(
                    next(data for kind, data in events if kind == "done")["status"],
                    "awaiting_approval",
                )
        self.assertTrue((self.root / "kb/outline/main.md").exists())
        self.assertTrue((self.root / "kb/outline/vol-01.md").exists())
        self.assertIsNone(self.request("GET", f"/sessions/{sid}/pending")["approval"])

    def wait(self, callback, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = callback()
            if predicate(value):
                return value
            time.sleep(0.05)
        self.fail(f"Timed out waiting for application state: {value}")

    def write(self, path, content, **options):
        return self.request(
            "PUT", self.url + "/file", {"path": path, "content": content, **options}
        )

    def search(self, query):
        return self.request("POST", self.url + "/search", {"query": query, "mode": "keyword"})[
            "results"
        ]

    def test_auth_and_project_open_reuses_workspace(self):
        self.assertEqual(httpx.get(self.base + "/projects").status_code, 401)
        again = self.request("POST", "/projects/open", {"path": str(self.root)})
        self.assertEqual(again["id"], self.pid)
        self.assertTrue(self.request("GET", self.url)["exists"])
        self.assertTrue(self.request("GET", self.url + "/tree"))

    def test_all_readonly_views_load(self):
        sid = self.session()
        for path in [
            "/overview",
            "/stats",
            "/usage",
            "/git/status",
            "/git/diff",
            "/git/changes",
            "/git/log",
            "/experts",
            "/skills",
            "/reviews",
            "/approvals",
            "/graph",
            "/timeline",
            "/knowledge-bases",
            "/chunks",
            "/kb-config",
            "/extract/status",
            "/extract/candidates",
            "/deconstruct/status",
        ]:
            with self.subTest(path=path):
                self.request("GET", self.url + path)
        for path in ["/context", "/messages", "/pending", "/approvals", "/run"]:
            self.request("GET", f"/sessions/{sid}" + path)
        for path in [
            "/domains",
            "/prompts",
            "/memory",
            "/usage/pricing",
            "/embeddings/options",
            "/mcp/status",
        ]:
            self.request("GET", path)

    def test_reviewer_key_is_masked(self):
        config = self.request("GET", "/config")
        self.assertEqual(config["reviewer"]["api_key"], "***")

    def test_reviewer_configuration_save_and_masked_roundtrip(self):
        saved = self.request(
            "PUT", "/config", {"reviewer": {"temperature": 0.37, "api_key": "***"}}
        )
        self.assertEqual(saved["reviewer"]["temperature"], 0.37)
        self.assertEqual(saved["reviewer"]["api_key"], "***")

    def test_invalid_config_is_client_error_and_preserves_previous(self):
        previous = self.request("GET", "/config")
        self.request("PUT", "/config", {"models": [{"id": ""}]}, status=422)
        self.assertEqual(self.request("GET", "/config"), previous)

    def test_invalid_model_window_is_reported_without_server_error(self):
        for role in ("writer", "extractor", "reviewer"):
            with self.subTest(role=role):
                self.request("PUT", "/config", {role: {"context_window": "invalid"}}, status=422)

    def test_filtered_chunk_count_matches_results_and_chinese_search_respects_limits(self):
        self.write("manuscript/ch-001.md", "---\nchapter: 1\n---\n\n" + BODY)
        self.write(
            "manuscript/ch-020.md",
            "---\nchapter: 20\n---\n\n他握紧了手中的旧剑。独有标记latechapter。",
        )
        chunks = self.request("GET", self.url + "/chunks", params={"q": "latechapter"})
        self.assertEqual(chunks["total"], 1)
        self.assertEqual(len(chunks["items"]), 1)
        results = self.request(
            "POST", self.url + "/search", {"query": "旧剑", "mode": "keyword", "chapter_limit": 1}
        )["results"]
        self.assertEqual([item["chapter"] for item in results], [1])

    def test_deleted_session_removes_regenerated_checkpoints(self):
        sid = self.session()
        self.chat(sid, "验证删除后的状态清理")
        self.events(self.client.post(f"/sessions/{sid}/regenerate"))
        self.request("DELETE", f"/sessions/{sid}")
        with closing(sqlite3.connect(self.home / "app.db")) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ? OR thread_id LIKE ?",
                (sid, sid + "-r%"),
            ).fetchone()[0]
        self.assertEqual(
            count, 0, "Deleted sessions must not leave original or regenerated checkpoints"
        )

    def test_rewrite_and_style_import_create_reusable_assets(self):
        result = self.request("POST", self.url + "/rewrite", {"text": BODY, "action": "polish"})
        self.assertTrue(result["text"])
        source = self.home / (self.pid + "-style.txt")
        source.write_text(BODY * 40, encoding="utf-8")
        result = self.request("POST", self.url + "/import-style", {"path": str(source)})
        self.assertTrue(result["expert"]["id"])
        self.assertTrue(result["skill"]["id"])
        self.assertTrue(self.request("GET", self.url + "/skills"))

    def test_vector_embedding_probe_reindex_and_search(self):
        config = self.request("GET", "/config")
        vector = {
            "provider": "openai",
            "base_url": config["writer"]["base_url"],
            "api_key": "test-only-key",
            "model": "integration-embedding",
            "dimensions": 8,
        }
        try:
            self.request("PUT", "/config", {"embedding": vector})
            probe = self.request("POST", "/embeddings/test", vector)
            self.assertTrue(probe["ok"], str(probe))
            self.assertEqual(probe["dim"], 8)
            self.write("manuscript/ch-001.md", BODY * 6)
            self.request("POST", self.url + "/reindex")
            status = self.wait(
                lambda: self.request("GET", self.url + "/index/status"),
                lambda value: not value["running"],
            )
            self.assertFalse(status["error"], str(status))
            self.assertGreater(status["embedded"], 0)
            results = self.request(
                "POST", self.url + "/search", {"query": "青石桥", "mode": "vector"}
            )["results"]
            self.assertTrue(results)
        finally:
            self.request("PUT", "/config", {"embedding": config["embedding"]})

    def test_chapter_edit_search_replace_export_and_versions(self):
        chapter = self.request("POST", self.url + "/chapter", {"title": "雨桥"})
        path = chapter["path"]
        content = "---\ntitle: 雨桥\nchapter: 1\n---\n\n" + BODY
        self.write(path, content)
        self.assertTrue(self.search("旧剑"), str(self.request("GET", self.url + "/chunks")))
        self.request("POST", self.url + "/git/commit", {"message": "初稿"})
        commit = self.request("GET", self.url + "/git/log")["items"][0]["hash"]
        preview = self.request(
            "POST", self.url + "/text-replace", {"query": "旧剑", "replacement": "长剑"}
        )
        self.assertEqual(preview["total"], 1)
        self.assertIn(
            "旧剑", self.request("GET", self.url + "/file", params={"path": path})["content"]
        )
        self.request(
            "POST",
            self.url + "/text-replace",
            {"query": "旧剑", "replacement": "长剑", "dry_run": False},
        )
        self.assertFalse(self.search("旧剑"))
        self.assertTrue(self.search("长剑"))
        exported = self.request(
            "POST",
            self.url + "/export/txt",
            {"path": str(self.home / (self.pid + ".txt")), "include_toc": True},
        )
        self.assertIn("长剑", Path(exported["path"]).read_text(encoding="utf-8-sig"))
        self.request("POST", self.url + "/git/restore", {"commit": commit, "path": path})
        self.assertIn(
            "旧剑", self.request("GET", self.url + "/file", params={"path": path})["content"]
        )
        self.wait(lambda: self.search("旧剑"), bool)
        self.assertEqual(self.request("GET", self.url + "/stats")["chapter"], 1)

    def test_file_conflict_rename_and_delete_keep_index_consistent(self):
        path = "manuscript/vol-01/ch-001.md"
        self.write(path, BODY)
        old = self.request("GET", self.url + "/file", params={"path": path})
        self.write(path, BODY + "钟声再响。")
        self.request(
            "PUT",
            self.url + "/file",
            {"path": path, "content": "过时内容", "expected_mtime": old["mtime"]},
            status=409,
        )
        renamed = "manuscript/vol-01/ch-002.md"
        self.request("POST", self.url + "/fs/rename", {"path": path, "new_path": renamed})
        self.assertTrue(self.search("旧剑"))
        self.request("DELETE", self.url + "/fs", params={"path": renamed})
        self.assertFalse(self.search("旧剑"))
        self.request("GET", self.url + "/file", params={"path": "../config.json"}, status=400)

    def test_kb_crud_graph_timeline_references_and_material_dedup(self):
        for kind in [
            "characters",
            "factions",
            "items",
            "locations",
            "world",
            "outline",
            "materials",
            "styles",
        ]:
            saved = self.request(
                "POST",
                self.url + f"/kb/{kind}",
                {
                    "id": "demo",
                    "meta": {"name": "林昭", "timeline": [{"chapter": 1, "state": "初入江湖"}]},
                    "body": BODY,
                },
            )
            self.assertEqual(saved["id"], "demo")
            self.assertTrue(self.request("GET", self.url + f"/kb/{kind}/demo"))
        self.assertTrue(self.search("林昭"))
        self.assertTrue(self.request("GET", self.url + "/graph")["nodes"])
        self.assertTrue(self.request("GET", self.url + "/timeline")["items"])
        self.assertTrue(
            self.request("GET", self.url + "/reference-candidates", params={"q": "林昭"})["items"]
        )
        self.request("POST", self.url + "/materials", {"title": "桥上雨声", "text": BODY})
        duplicate = self.request(
            "POST", self.url + "/materials", {"title": "另一标题", "text": BODY}
        )
        self.assertTrue(duplicate["duplicate"])
        self.request("DELETE", self.url + "/kb/characters/demo")
        self.request("GET", self.url + "/kb/characters/demo", status=404)

    def test_real_graph_chat_checkpoint_regeneration_and_usage(self):
        sid = self.session()
        events = self.chat(sid, "你好，这是集成测试。")
        self.assertNotIn("error", [kind for kind, _ in events], str(events))
        messages = self.request("GET", f"/sessions/{sid}/messages")
        self.assertEqual([m["role"] for m in messages], ["user", "assistant"])
        self.assertIn("测试回复", messages[-1]["content"])
        events = self.events(self.client.post(f"/sessions/{sid}/regenerate"))
        self.assertNotIn("error", [kind for kind, _ in events], str(events))
        self.assertEqual(len(self.request("GET", f"/sessions/{sid}/messages")), 2)
        self.assertGreater(self.request("GET", self.url + "/usage")["totals"]["total"], 0)

    def test_approval_accept_edit_and_reject_real_tools(self):
        for decision in ["approve", "edit", "reject"]:
            with self.subTest(decision=decision):
                sid = self.session(permission_mode="default")
                entity_id = "role-" + decision
                self.tool(
                    sid,
                    "kb_write",
                    {
                        "kind": "characters",
                        "entity_id": entity_id,
                        "meta_json": '{"name":"林昭"}',
                        "body": BODY,
                    },
                )
                pending = self.request("GET", f"/sessions/{sid}/pending")["approval"]
                self.assertIsNotNone(pending)
                self.assertFalse((self.root / f"kb/characters/{entity_id}.md").exists())
                item = {"type": decision}
                if decision == "edit":
                    item["edited_action"] = {
                        "name": "kb_write",
                        "args": {**pending["requests"][0]["raw_args"], "body": "人工编辑后的设定"},
                    }
                events = self.events(
                    self.client.post("/chat/approve", json={"session_id": sid, "decisions": [item]})
                )
                self.assertNotIn("error", [kind for kind, _ in events], str(events))
                self.assertIsNone(self.request("GET", f"/sessions/{sid}/pending")["approval"])
                target = self.root / f"kb/characters/{entity_id}.md"
                self.assertEqual(target.exists(), decision != "reject")
                if decision == "edit":
                    self.assertIn("人工编辑", target.read_text(encoding="utf-8"))

    def test_side_question_cannot_write_through_builtin_tool(self):
        sid = self.session(kind="side")
        events = self.tool(
            sid,
            "write_file",
            {"file_path": "/manuscript/side.md", "content": "不能落盘"},
            mode="side",
        )
        self.assertFalse((self.root / "manuscript/side.md").exists(), str(events))
        self.assertIsNone(self.request("GET", f"/sessions/{sid}/pending")["approval"])

    def test_disconnect_snapshot_steering_and_stop_preserve_user_messages(self):
        sid = self.session()
        with self.client.stream(
            "POST", "/chat", json={"session_id": sid, "message": "TEST_SLOW 保留原请求"}
        ) as response:
            next(response.iter_lines())
        snapshot = self.request("GET", f"/sessions/{sid}/run")
        self.assertTrue(snapshot["running"])
        self.request("POST", "/chat/steer", {"session_id": sid, "message": "请保留引导消息。"})
        self.request("POST", f"/sessions/{sid}/run/stop")
        self.wait(
            lambda: self.request("GET", f"/sessions/{sid}/run"), lambda value: not value["running"]
        )
        messages = self.request("GET", f"/sessions/{sid}/messages")
        self.assertIn("TEST_SLOW 保留原请求", [m["content"] for m in messages])
        self.assertIn("请保留引导消息。", [m["content"] for m in messages])

    def test_active_session_cannot_be_deleted(self):
        sid = self.session()
        with self.client.stream(
            "POST", "/chat", json={"session_id": sid, "message": "TEST_SLOW 删除保护"}
        ) as response:
            next(response.iter_lines())
        try:
            self.request("DELETE", f"/sessions/{sid}", status=409)
        finally:
            self.request("POST", f"/sessions/{sid}/run/stop")

    def test_active_workspace_cannot_be_purged(self):
        sid = self.session()
        with self.client.stream(
            "POST", "/chat", json={"session_id": sid, "message": "TEST_SLOW 空间删除保护"}
        ) as response:
            next(response.iter_lines())
        try:
            self.request("DELETE", self.url, params={"purge": True}, status=409)
            self.assertTrue(self.root.exists())
        finally:
            self.request("POST", f"/sessions/{sid}/run/stop")

    def test_missing_session_chat_returns_404(self):
        self.request("POST", "/chat", {"session_id": "missing", "message": "你好"}, status=404)

    def test_model_error_is_saved_and_next_request_can_recover(self):
        sid = self.session()
        events = self.chat(sid, "TEST_ERROR")
        self.assertIn("error", [kind for kind, _ in events])
        self.assertEqual(
            self.request("GET", f"/sessions/{sid}/messages")[0]["content"], "TEST_ERROR"
        )
        events = self.chat(sid, "恢复普通对话")
        self.assertNotIn("error", [kind for kind, _ in events], str(events))

    def test_review_edit_invalidates_status(self):
        path = "manuscript/vol-01/ch-001.md"
        self.write(path, "---\ntitle: 雨桥\nchapter: 1\n---\n\n" + BODY * 12)
        result = self.request("POST", self.url + "/review", {"chapter": "vol-01/ch-001.md"})
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(self.request("GET", self.url + "/reviews")[0]["status"], "pass")
        current = self.request("GET", self.url + "/file", params={"path": path})
        self.write(path, current["content"] + "桥下忽然传来脚步声。")
        self.assertEqual(self.request("GET", self.url + "/reviews")[0]["status"], "stale")

    def test_import_extract_candidates_and_deconstruct(self):
        source = self.home / (self.pid + "-source.txt")
        source.write_text(
            "第一章 雨桥\n" + BODY * 8 + "\n第二章 钟声\n" + BODY * 8, encoding="utf-8"
        )
        preview = self.request("POST", self.url + "/import/preview", {"path": str(source)})
        self.assertEqual(len(preview["chapters"]), 2)
        self.request("POST", self.url + "/import", {"path": str(source)})
        self.wait(
            lambda: self.request("GET", self.url + "/index/status"),
            lambda value: not value["running"],
        )
        self.request("POST", self.url + "/extract", {"limit": 2})
        status = self.wait(
            lambda: self.request("GET", self.url + "/extract/status"),
            lambda value: not value["running"],
        )
        self.assertFalse(status["run"].get("error"), str(status))
        self.assertTrue(self.request("GET", self.url + "/kb/characters"))
        candidates = self.request("GET", self.url + "/extract/candidates")["items"]
        self.assertTrue(candidates)
        self.request("POST", self.url + f"/extract/candidates/{candidates[0]['id']}/accept")
        self.request("POST", self.url + "/deconstruct", {"source": str(source), "groups": 1})
        status = self.wait(
            lambda: self.request("GET", self.url + "/deconstruct/status"),
            lambda value: value["status"] != "running",
        )
        self.assertEqual(status["status"], "done", str(status))
        self.assertTrue(self.request("GET", self.url + "/kb/materials"))

    def test_memory_expert_and_skill_persist_into_context(self):
        self.request(
            "PUT", "/memory/project", {"project_id": self.pid, "content": "- 本书使用第三人称。"}
        )
        self.request(
            "POST",
            self.url + "/experts",
            {
                "id": "integration-expert",
                "meta": {"name": "集成测试专家"},
                "body": "节奏克制，注重人物行动。",
            },
        )
        self.write(
            "skills/rhythm/SKILL.md",
            "---\nname: 场景节奏\ndescription: 场景节奏测试技能\n---\n用行动组织场景。",
        )
        sid = self.session(expert_id="integration-expert")
        context = json.dumps(self.request("GET", f"/sessions/{sid}/context"), ensure_ascii=False)
        self.assertIn("第三人称", context)
        self.assertIn("节奏克制", context)
        self.assertTrue(self.request("GET", self.url + "/skills"))
        self.request("DELETE", self.url + "/experts/integration-expert")

    def test_concurrent_chapter_creation_allocates_unique_numbers(self):
        def create(index):
            return self.client.post(self.url + "/chapter", json={"title": f"并发章{index}"})

        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(create, range(6)))
        self.assertEqual([response.status_code for response in responses], [200] * 6)
        self.assertEqual(len({response.json()["chapter"] for response in responses}), 6)
