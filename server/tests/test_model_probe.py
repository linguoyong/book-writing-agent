from __future__ import annotations

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import model_probe, security
from app.api.routes import system
from app.config import ModelProfile, ModelSettings, Settings, ensure_models
from app.main import app


class ModelProbeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                cls.requests.append((self.path, self.headers.get("Authorization"), body))
                model = body["model"]
                status = 200
                if model.startswith("error-"):
                    status = int(model.split("-")[1])
                elif model == "reject-stream-options" and "stream_options" in body:
                    status = 400
                if model == "slow":
                    time.sleep(0.2)
                if status != 200:
                    payload = json.dumps(
                        {
                            "error": {
                                "message": "stream_options invalid; secret test-stored-writer",
                                "type": "invalid_request_error",
                            }
                        }
                    ).encode()
                else:
                    delta = {"content": "OK"}
                    if model == "reasoning":
                        delta = {"reasoning_content": "thinking"}
                    chunk = {
                        "id": "probe",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": model,
                        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                    }
                    payload = (
                        ("data: " + json.dumps(chunk) + "\n\n") if model != "empty" else ""
                    ).encode() + b"data: [DONE]\n\n"
                self.send_response(status)
                self.send_header(
                    "Content-Type", "text/event-stream" if status == 200 else "application/json"
                )
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self.requests.clear()
        self.saved = ensure_models(
            Settings(
                models=[
                    ModelProfile(
                        id="default",
                        base_url=self.url,
                        model="stored-writer",
                        api_key="test-stored-writer",
                    ),
                    ModelProfile(
                        id="second",
                        base_url=self.url,
                        model="stored-second",
                        api_key="test-stored-second",
                    ),
                ],
                active_model_id="default",
                extractor=ModelSettings(
                    base_url=self.url, model="stored-extractor", api_key="test-stored-extractor"
                ),
                reviewer=ModelSettings(
                    base_url=self.url, model="stored-reviewer", api_key="test-stored-reviewer"
                ),
            )
        )
        self.original = self.saved.model_dump()
        self.config_patch = patch.object(system, "load_settings", return_value=self.saved)
        self.config_patch.start()
        self.client = TestClient(app, headers={security.AUTH_HEADER: security.api_token()})

    def tearDown(self):
        self.client.close()
        self.config_patch.stop()
        self.assertEqual(self.saved.model_dump(), self.original)

    def probe(self, role="writer", model="draft-model", key="draft-key", **extra):
        response = self.client.post(
            "/api/models/test",
            json={
                "role": role,
                "model_id": "default",
                "settings": {
                    "base_url": self.url,
                    "api_key": key,
                    "model": model,
                    "temperature": 0.3,
                    "reasoning_effort": "high",
                },
                **extra,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_unsaved_writer_configuration_makes_real_streaming_request(self):
        result = self.probe()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["model"], "draft-model")
        self.assertGreaterEqual(result["ms"], 0)
        path, auth, body = self.requests[-1]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(auth, "Bearer draft-key")
        self.assertTrue(body["stream"])
        self.assertEqual(body["temperature"], 0.3)
        self.assertEqual(body["reasoning_effort"], "high")
        self.assertEqual(body["messages"], [{"content": "请只回复 OK。", "role": "user"}])

    def test_masked_keys_are_resolved_by_model_id_or_role(self):
        for role, model_id, expected in [
            ("writer", "second", "test-stored-second"),
            ("extractor", "default", "test-stored-extractor"),
            ("reviewer", "default", "test-stored-reviewer"),
        ]:
            with self.subTest(role=role):
                result = self.probe(role, key="***", model_id=model_id)
                self.assertTrue(result["ok"], result)
                self.assertEqual(self.requests[-1][1], f"Bearer {expected}")
                self.assertNotIn(expected, json.dumps(result))

    def test_reviewer_fallback_uses_unsaved_default_model(self):
        fallback = self.saved.models[1].model_dump()
        fallback.update(model="unsaved-default", api_key="***")
        result = self.probe("reviewer", model="", key="***", fallback_model=fallback)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["model"], "unsaved-default")
        self.assertEqual(self.requests[-1][1], "Bearer test-stored-second")

    def test_reviewer_fallback_without_draft_uses_saved_default(self):
        result = self.probe("reviewer", model="")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["model"], "stored-writer")

    def test_cleared_key_does_not_reuse_saved_key(self):
        result = self.probe(key="")
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.requests[-1][1], "Bearer not-needed")

    def test_unknown_masked_key_is_rejected_before_network_request(self):
        result = self.probe(key="***", model_id="new-unsaved-id")
        self.assertFalse(result["ok"])
        self.assertIn("API Key", result["error"])
        self.assertEqual(self.requests, [])

    def test_invalid_configuration_is_rejected_without_network(self):
        for base, model in [
            (self.url, ""),
            ("", "m"),
            ("file:///tmp/x", "m"),
            ("https://user:password@example.com/v1", "m"),
            ("http://127.0.0.1:invalid/v1", "m"),
        ]:
            with self.subTest(base=base):
                result = self.probe(settings={"base_url": base, "model": model})
                self.assertFalse(result["ok"], result)
        self.assertEqual(self.requests, [])

    def test_service_errors_are_readable_and_do_not_echo_secrets(self):
        for status, hint in [
            (401, "认证失败"),
            (403, "权限"),
            (404, "模型"),
            (429, "额度"),
            (400, "HTTP 400"),
            (503, "HTTP 503"),
        ]:
            with self.subTest(status=status):
                result = self.probe(model=f"error-{status}")
                self.assertFalse(result["ok"])
                self.assertIn(hint, result["error"])
                self.assertNotIn("test-stored-writer", json.dumps(result))

    def test_stream_options_compatibility_fallback_works_in_probe(self):
        result = self.probe(model="reject-stream-options")
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(self.requests), 2)
        self.assertIn("stream_options", self.requests[0][2])
        self.assertNotIn("stream_options", self.requests[1][2])

    def test_reasoning_without_answer_is_not_reported_as_success(self):
        self.assertFalse(self.probe(model="reasoning")["ok"])

    def test_empty_response_is_not_reported_as_success(self):
        result = self.probe(model="empty")
        self.assertFalse(result["ok"])
        self.assertIn("内容", result["error"])

    def test_timeout_is_bounded_without_retries(self):
        with patch.object(model_probe, "PROBE_TIMEOUT", 0.05):
            result = self.probe(model="slow")
        self.assertFalse(result["ok"])
        self.assertIn("超时", result["error"])
        self.assertLessEqual(len(self.requests), 1)

    def test_probe_requires_local_api_authentication(self):
        if security.auth_disabled():
            self.skipTest("Authentication disabled by test environment")
        response = TestClient(app).post("/api/models/test", json={})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.requests, [])
