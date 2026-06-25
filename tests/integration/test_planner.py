"""Integration tests for the Planner agent FastAPI app.

The A2A delegate call to the worker is patched so tests are fully offline.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.conftest import make_mock_llm

VALID_TOKEN = "planner-dev-token"
AUTH = {"Authorization": f"Bearer {VALID_TOKEN}"}

_WORKER_ANSWER = "This is the worker's answer."

# Mock httpx response for the agent card fetch
def _mock_card_response():
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = {"name": "Mock Worker", "url": "http://worker:8001"}
    return r


# Mock httpx response for tasks/send (non-streaming)
def _mock_task_response():
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = {
        "jsonrpc": "2.0",
        "id": "req-test",
        "result": {
            "id": "test",
            "status": {
                "state": "completed",
                "message": {
                    "role": "agent",
                    "parts": [{"type": "text", "text": _WORKER_ANSWER}],
                },
            },
        },
    }
    return r


@pytest.fixture(scope="module")
def planner_client():
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.get = AsyncMock(return_value=_mock_card_response())
    mock_http.post = AsyncMock(return_value=_mock_task_response())

    with patch("httpx.AsyncClient", return_value=mock_http):
        import planner.main as pm
        yield TestClient(pm.app, raise_server_exceptions=False)


class TestPlannerAgentCard:
    def test_agent_card_accessible(self, planner_client):
        resp = planner_client.get("/.well-known/agent.json")
        assert resp.status_code == 200

    def test_agent_card_has_name(self, planner_client):
        data = planner_client.get("/.well-known/agent.json").json()
        assert data["name"]


class TestPlannerHealth:
    def test_health_ok(self, planner_client):
        resp = planner_client.get("/health")
        assert resp.status_code == 200


class TestPlannerAsk:
    def test_ask_requires_auth(self, planner_client):
        resp = planner_client.post("/ask", json={"question": "test"})
        assert resp.status_code == 401

    def test_ask_with_valid_token(self, planner_client):
        resp = planner_client.post(
            "/ask",
            json={"question": "What is Docker?"},
            headers=AUTH,
        )
        assert resp.status_code == 200

    def test_ask_returns_question_and_answer(self, planner_client):
        resp = planner_client.post(
            "/ask",
            json={"question": "What is Docker?"},
            headers=AUTH,
        )
        body = resp.json()
        assert "question" in body
        assert "answer" in body

    def test_ask_answer_is_non_empty(self, planner_client):
        resp = planner_client.post(
            "/ask",
            json={"question": "What is Python?"},
            headers=AUTH,
        )
        assert resp.json()["answer"]


class TestPlannerUI:
    def test_ui_accessible_without_auth(self, planner_client):
        resp = planner_client.get("/ui")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
