"""Integration tests for the Worker agent FastAPI app.

Uses TestClient — no real server, no real LLM calls (patched via mock_llm).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Patch build_client BEFORE importing worker.main so the app builds with a mock.
from tests.conftest import make_mock_llm

_MOCK_CLIENT = make_mock_llm("Worker mock answer.")


@pytest.fixture(scope="module")
def worker_client():
    with patch("shared.model_factory.build_client", return_value=_MOCK_CLIENT):
        import worker.main as wm
        importlib_reload_if_needed(wm)
        yield TestClient(wm.app, raise_server_exceptions=False)


def importlib_reload_if_needed(module):
    """No-op helper; module is already imported fresh in this process."""
    pass


VALID_TOKEN = "worker-dev-token"
AUTH = {"Authorization": f"Bearer {VALID_TOKEN}"}


def _send_payload(task_id: str = "t1", question: str = "What is AI?", method: str = "tasks/send") -> dict:
    return {
        "jsonrpc": "2.0",
        "id": f"req-{task_id}",
        "method": method,
        "params": {
            "id": task_id,
            "message": {"role": "user", "parts": [{"type": "text", "text": question}]},
        },
    }


class TestAgentCard:
    def test_agent_card_accessible_without_auth(self, worker_client):
        resp = worker_client.get("/.well-known/agent.json")
        assert resp.status_code == 200

    def test_agent_card_has_required_fields(self, worker_client):
        data = worker_client.get("/.well-known/agent.json").json()
        assert "name" in data
        assert "url" in data
        assert "capabilities" in data
        assert "skills" in data

    def test_agent_card_streaming_capability(self, worker_client):
        data = worker_client.get("/.well-known/agent.json").json()
        assert data["capabilities"]["streaming"] is True


class TestHealth:
    def test_health_accessible_without_auth(self, worker_client):
        resp = worker_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestA2AAuth:
    def test_a2a_without_auth_rejected(self, worker_client):
        resp = worker_client.post("/", json=_send_payload())
        assert resp.status_code == 401

    def test_a2a_with_valid_token_accepted(self, worker_client):
        resp = worker_client.post("/", json=_send_payload(), headers=AUTH)
        assert resp.status_code == 200


class TestTasksSend:
    def test_tasks_send_returns_jsonrpc(self, worker_client):
        resp = worker_client.post("/", json=_send_payload(), headers=AUTH)
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert "result" in body

    def test_tasks_send_has_completed_state(self, worker_client):
        resp = worker_client.post("/", json=_send_payload(), headers=AUTH)
        status = resp.json()["result"]["status"]
        assert status["state"] == "completed"

    def test_tasks_send_has_answer_text(self, worker_client):
        resp = worker_client.post("/", json=_send_payload(), headers=AUTH)
        parts = resp.json()["result"]["status"]["message"]["parts"]
        assert len(parts) >= 1
        assert parts[0]["type"] == "text"
        assert parts[0]["text"]

    def test_unsupported_method_returns_error(self, worker_client):
        payload = _send_payload(method="tasks/unknown")
        resp = worker_client.post("/", json=payload, headers=AUTH)
        assert resp.status_code in (200, 400)
        body = resp.json()
        assert "error" in body

    def test_jsonrpc_id_echoed(self, worker_client):
        payload = _send_payload(task_id="echo-test")
        resp = worker_client.post("/", json=payload, headers=AUTH)
        assert resp.json()["id"] == "req-echo-test"
