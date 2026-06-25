"""Tests for shared/auth.py — BearerAuthMiddleware."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from shared.auth import BearerAuthMiddleware


def _make_app(valid_tokens: set[str]) -> TestClient:
    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware, valid_tokens=valid_tokens)

    @app.get("/protected")
    async def protected():
        return {"ok": True}

    @app.get("/.well-known/agent.json")
    async def card():
        return {"name": "Test Agent"}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/ui")
    async def ui():
        return {"ui": True}

    return TestClient(app, raise_server_exceptions=False)


TOKENS = {"token-abc", "token-xyz"}


class TestBearerAuth:
    def setup_method(self):
        self.client = _make_app(TOKENS)

    def test_valid_token_passes(self):
        resp = self.client.get("/protected", headers={"Authorization": "Bearer token-abc"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_second_valid_token_passes(self):
        resp = self.client.get("/protected", headers={"Authorization": "Bearer token-xyz"})
        assert resp.status_code == 200

    def test_invalid_token_rejected(self):
        resp = self.client.get("/protected", headers={"Authorization": "Bearer bad-token"})
        assert resp.status_code == 401

    def test_missing_header_rejected(self):
        resp = self.client.get("/protected")
        assert resp.status_code == 401

    def test_wrong_scheme_rejected(self):
        resp = self.client.get("/protected", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 401

    def test_error_body_is_jsonrpc(self):
        resp = self.client.get("/protected")
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert "error" in body
        assert body["error"]["code"] == -32001

    def test_agent_card_bypasses_auth(self):
        resp = self.client.get("/.well-known/agent.json")
        assert resp.status_code == 200

    def test_health_bypasses_auth(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200

    def test_ui_bypasses_auth(self):
        resp = self.client.get("/ui")
        assert resp.status_code == 200

    def test_www_authenticate_header_on_rejection(self):
        resp = self.client.get("/protected")
        assert "WWW-Authenticate" in resp.headers
