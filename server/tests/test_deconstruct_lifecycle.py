from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import common
from app.api.routes import deconstruct as routes
from app.text import save_text


class DeconstructLifecycleTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "source.txt"
        save_text(self.source, "source")
        app = FastAPI()
        app.include_router(routes.router, prefix="/api")
        self.client = TestClient(app)
        for module in (common, routes):
            patcher = patch.object(
                module, "_require_project", return_value={"path": str(self.root)}
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        common._deconstruct_jobs.clear()
        common._deconstruct_stop.clear()
        self.addCleanup(common._deconstruct_jobs.clear)
        self.addCleanup(common._deconstruct_stop.clear)
        self.url = "/api/projects/test/deconstruct"

    def start(self):
        response = self.client.post(self.url, json={"source": str(self.source)})
        self.assertEqual(response.status_code, 200, response.text)

    def wait_finished(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            job = self.client.get(self.url + "/status").json()
            if job["status"] != "running":
                return job
            time.sleep(0.01)
        self.fail("deconstruct worker did not finish")

    def test_route_runs_real_worker_and_error_allows_retry(self):
        with patch("app.deconstruct.run", side_effect=RuntimeError("model failed")) as run:
            self.start()
            job = self.wait_finished()
            self.assertEqual(job["status"], "error")
            self.assertIn("model failed", job["error"])
            run.assert_called_once()
        with patch("app.deconstruct.run", return_value={"groups": 1}) as run:
            self.start()
            self.assertEqual(self.wait_finished()["status"], "done")
            self.assertTrue(run.call_args.kwargs["allow_external"])

    def test_stop_and_duplicate_start(self):
        entered, release = threading.Event(), threading.Event()

        def run(*args, **kwargs):
            entered.set()
            release.wait(3)
            self.assertTrue(kwargs["should_stop"]())
            return {"groups": 0}

        with patch("app.deconstruct.run", side_effect=run):
            try:
                self.start()
                self.assertTrue(entered.wait(2))
                response = self.client.post(self.url, json={"source": str(self.source)})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(self.client.post(self.url + "/stop").status_code, 200)
            finally:
                release.set()
            self.assertEqual(self.wait_finished()["status"], "stopped")
            self.assertNotIn("test", common._deconstruct_stop)
