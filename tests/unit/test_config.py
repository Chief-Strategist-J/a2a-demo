"""Tests for shared/config.py — YAML loading and env var interpolation."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from shared.config import _load_raw, load, AppCfg


ROOT = Path(__file__).parent.parent.parent
CONFIG = ROOT / "config.yaml"


class TestEnvInterpolation:
    def test_substitutes_env_var(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_VAR", "hello")
        raw = {"key": "${MY_TEST_VAR}"}
        import yaml, io
        # Write a temp file
        tmp = Path("/tmp/test_interp.yaml")
        tmp.write_text(yaml.dump(raw))
        result = _load_raw(tmp)
        assert result["key"] == "hello"

    def test_uses_default_when_var_missing(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_VAR_123", raising=False)
        raw = {"key": "${NONEXISTENT_VAR_123:fallback_value}"}
        tmp = Path("/tmp/test_default.yaml")
        tmp.write_text(yaml.dump(raw))
        result = _load_raw(tmp)
        assert result["key"] == "fallback_value"

    def test_empty_default_when_no_default_specified(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR_456", raising=False)
        raw = {"key": "${MISSING_VAR_456}"}
        tmp = Path("/tmp/test_empty.yaml")
        tmp.write_text(yaml.dump(raw))
        result = _load_raw(tmp)
        assert result["key"] == ""

    def test_nested_interpolation(self, monkeypatch):
        monkeypatch.setenv("NESTED_HOST", "myhost")
        raw = {"url": "http://${NESTED_HOST:localhost}:8000"}
        tmp = Path("/tmp/test_nested.yaml")
        tmp.write_text(yaml.dump(raw))
        result = _load_raw(tmp)
        assert result["url"] == "http://myhost:8000"

    def test_interpolation_in_list(self, monkeypatch):
        monkeypatch.setenv("LIST_VAL", "item1")
        raw = {"items": ["${LIST_VAL}", "item2"]}
        tmp = Path("/tmp/test_list.yaml")
        tmp.write_text(yaml.dump(raw))
        result = _load_raw(tmp)
        assert result["items"][0] == "item1"


class TestConfigLoad:
    def test_loads_real_config(self):
        cfg = load(CONFIG)
        assert isinstance(cfg, AppCfg)

    def test_planner_agent_present(self):
        cfg = load(CONFIG)
        assert "planner" in cfg.agents

    def test_worker_agent_present(self):
        cfg = load(CONFIG)
        assert "worker" in cfg.agents

    def test_planner_has_model(self):
        cfg = load(CONFIG)
        model = cfg.agents["planner"].model
        assert model.provider in ("groq", "gemini", "openrouter", "ollama")
        assert model.model_id

    def test_worker_has_flow(self):
        cfg = load(CONFIG)
        flow = cfg.agents["worker"].flow
        assert flow.entry
        assert len(flow.nodes) >= 1
        assert isinstance(flow.edges, list)

    def test_auth_config(self):
        cfg = load(CONFIG)
        assert isinstance(cfg.auth.enabled, bool)
        assert isinstance(cfg.auth.tokens, dict)

    def test_worker_tools_list(self):
        cfg = load(CONFIG)
        tool_names = [t.name for t in cfg.agents["worker"].tools]
        assert "calculator" in tool_names
        assert "web_search" in tool_names

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load("/nonexistent/config.yaml")
