"""Prompt library loader.

Usage:
    from shared.prompts import load, render

    load("prompts.yaml")          # call once at startup
    text = render("worker_default", {"agent_name": "Worker", "current_date": "2026-06-25"})

Templates use {{variable}} placeholders. Missing variables raise KeyError.
Unknown prompt ids raise KeyError.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

_REGISTRY: dict[str, dict] = {}
_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


def load(path: str | Path = "prompts.yaml") -> None:
    """Load prompts from a YAML file into the in-process registry."""
    with open(path) as f:
        data = yaml.safe_load(f)
    for pid, prompt in (data.get("prompts") or {}).items():
        _REGISTRY[pid] = prompt


def render(prompt_id: str, variables: dict[str, Any] | None = None) -> str:
    """Render a prompt template, substituting {{variable}} placeholders.

    Raises KeyError if the prompt_id is unknown or a required variable is missing.
    """
    if prompt_id not in _REGISTRY:
        raise KeyError(
            f"Unknown prompt id '{prompt_id}'. Available: {list(_REGISTRY)}"
        )
    template: str = _REGISTRY[prompt_id]["template"].rstrip()
    vars_ = variables or {}

    # Detect which variables the template needs
    required = set(_VAR_RE.findall(template))
    missing = required - vars_.keys()
    if missing:
        raise KeyError(
            f"Prompt '{prompt_id}' requires variables {sorted(missing)} "
            f"but only {sorted(vars_.keys())} were provided."
        )

    def _sub(m: re.Match) -> str:
        return str(vars_[m.group(1)])

    return _VAR_RE.sub(_sub, template)


def standard_vars(agent_name: str) -> dict[str, str]:
    """Return the standard injection variables (date + agent name)."""
    return {
        "agent_name": agent_name,
        "current_date": date.today().isoformat(),
    }


def list_prompts() -> list[str]:
    return list(_REGISTRY)


def is_loaded() -> bool:
    return bool(_REGISTRY)
