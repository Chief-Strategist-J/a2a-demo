"""Tests for shared/tools/ — registry, calculator, web_search."""
from __future__ import annotations

import pytest

import shared.tools.calculator
import shared.tools.web_search
from shared.tools.registry import Tool, get_enabled, list_all, _REGISTRY


class TestRegistry:
    def test_calculator_registered(self):
        assert "calculator" in list_all()

    def test_web_search_registered(self):
        assert "web_search" in list_all()

    def test_get_enabled_returns_only_enabled(self):
        cfgs = [
            {"name": "calculator", "enabled": True},
            {"name": "web_search", "enabled": False},
        ]
        enabled = get_enabled(cfgs)
        assert len(enabled) == 1
        assert enabled[0].name == "calculator"

    def test_get_enabled_empty_when_none_enabled(self):
        cfgs = [{"name": "calculator", "enabled": False}]
        assert get_enabled(cfgs) == []

    def test_get_enabled_skips_unknown_tools(self):
        cfgs = [{"name": "nonexistent_tool_xyz", "enabled": True}]
        assert get_enabled(cfgs) == []

    def test_tool_openai_schema_structure(self):
        tool = _REGISTRY["calculator"]
        schema = tool.openai_schema()
        assert schema["type"] == "function"
        assert "function" in schema
        assert schema["function"]["name"] == "calculator"
        assert "parameters" in schema["function"]


class TestCalculator:
    def _calc(self, expr: str) -> str:
        return _REGISTRY["calculator"].run(expression=expr)

    def test_addition(self):
        result = self._calc("2 + 3")
        assert "5" in result

    def test_subtraction(self):
        result = self._calc("10 - 4")
        assert "6" in result

    def test_multiplication(self):
        result = self._calc("3 * 7")
        assert "21" in result

    def test_division(self):
        result = self._calc("10 / 4")
        assert "2.5" in result

    def test_power(self):
        result = self._calc("2 ** 8")
        assert "256" in result

    def test_modulo(self):
        result = self._calc("10 % 3")
        assert "1" in result

    def test_parentheses(self):
        result = self._calc("(2 + 3) * 4")
        assert "20" in result

    def test_whole_number_display(self):
        # Whole-number results display without decimal
        result = self._calc("4.0 + 6.0")
        assert "10" in result
        assert "10.0" not in result

    def test_invalid_expression_returns_error(self):
        result = self._calc("import os")
        assert "Error" in result

    def test_division_by_zero(self):
        result = self._calc("1 / 0")
        assert "Error" in result or "inf" in result.lower() or "division" in result.lower()

    def test_empty_expression(self):
        result = self._calc("")
        assert "Error" in result

    def test_nested_parentheses(self):
        result = self._calc("((2 + 3) * (4 - 1)) / 5")
        assert "3" in result


class TestWebSearch:
    def test_stub_returns_message_without_key(self, monkeypatch):
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        result = _REGISTRY["web_search"].run(query="test query")
        assert "test query" in result
        assert "BRAVE_API_KEY" in result

    def test_stub_includes_query(self, monkeypatch):
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        result = _REGISTRY["web_search"].run(query="python programming")
        assert "python programming" in result
