from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import security


class AuthMiddlewareTest(unittest.TestCase):
    def setUp(self) -> None:
        self._disabled = security._DISABLED
        self._token = security._TOKEN
        security._DISABLED = False
        security._TOKEN = "unit-token"

        app = FastAPI()

        @app.get("/api/health")
        def health() -> dict[str, str]:
            return {"status": "ok"}

        @app.get("/api/private")
        def private() -> dict[str, bool]:
            return {"ok": True}

        app.add_middleware(security.AuthMiddleware)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        security._DISABLED = self._disabled
        security._TOKEN = self._token

    def test_health_is_public(self) -> None:
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_missing_token_is_rejected(self) -> None:
        self.assertEqual(self.client.get("/api/private").status_code, 401)

    def test_wrong_token_is_rejected(self) -> None:
        response = self.client.get(
            "/api/private", headers={security.AUTH_HEADER: "wrong"}
        )
        self.assertEqual(response.status_code, 401)

    def test_correct_token_is_allowed(self) -> None:
        response = self.client.get(
            "/api/private", headers={security.AUTH_HEADER: "unit-token"}
        )
        self.assertEqual(response.status_code, 200)

    def test_disabled_auth_lets_requests_through(self) -> None:
        security._DISABLED = True
        self.assertEqual(self.client.get("/api/private").status_code, 200)


if __name__ == "__main__":
    unittest.main()
