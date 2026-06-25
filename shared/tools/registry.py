"""Tool registry.

Define a tool:
    @register(name="my_tool", description="…", parameters={…})
    def my_tool(arg: str) -> str:
        return "result"

Use in graph_builder:
    enabled_tools = get_enabled(tool_cfgs)   # returns list[Tool]
    openai_schemas = [t.openai_schema() for t in enabled_tools]
"""
from __future__ import annotations

from typing import Any, Callable

_REGISTRY: dict[str, "Tool"] = {}


class Tool:
    def __init__(self, name: str, description: str, parameters: dict, fn: Callable) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self._fn = fn

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def run(self, **kwargs: Any) -> str:
        return str(self._fn(**kwargs))


def register(name: str, description: str, parameters: dict) -> Callable:
    def _decorator(fn: Callable) -> Callable:
        _REGISTRY[name] = Tool(name, description, parameters, fn)
        return fn
    return _decorator


def get_enabled(tool_cfgs: list[dict]) -> list[Tool]:
    """Return Tool objects for tools enabled in agent config."""
    return [
        _REGISTRY[tc["name"]]
        for tc in tool_cfgs
        if tc.get("enabled") and tc["name"] in _REGISTRY
    ]


def list_all() -> list[str]:
    return list(_REGISTRY.keys())
