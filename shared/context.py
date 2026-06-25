"""Context manager for LLM calls.

Loads context.yaml and provides:
  - Input validation (length, empty check)
  - Message list construction (system + user)
  - Output validation (empty, min/max length)
  - Standard variable injection for prompt templates
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ContextError(ValueError):
    """Raised when input or output fails validation."""


class ContextManager:
    def __init__(self, agent_id: str, cfg: dict) -> None:
        self._agent_id = agent_id
        self._cfg = cfg

    # ── factories ────────────────────────────────────────────

    @classmethod
    def load(cls, path: str | Path = "context.yaml") -> dict[str, "ContextManager"]:
        """Load context.yaml and return a dict of ContextManager per agent."""
        with open(path) as f:
            data = yaml.safe_load(f)

        defaults = data.get("defaults", {})
        managers: dict[str, ContextManager] = {}

        for agent_id, agent_cfg in (data.get("agents") or {}).items():
            merged = _deep_merge(defaults, agent_cfg)
            managers[agent_id] = cls(agent_id, merged)

        # Build a default manager for agents not explicitly listed
        managers["__default__"] = cls("__default__", defaults)
        return managers

    @classmethod
    def default(cls) -> "ContextManager":
        return cls("default", _HARD_DEFAULTS)

    # ── input ────────────────────────────────────────────────

    def validate_input(self, question: str) -> str:
        inp = self._cfg.get("input", {})

        if inp.get("strip_whitespace", True):
            question = question.strip()

        if inp.get("reject_empty", True) and not question:
            raise ContextError("Question must not be empty.")

        max_len = inp.get("max_length", 4000)
        if len(question) > max_len:
            raise ContextError(
                f"Question length {len(question)} exceeds limit of {max_len} characters."
            )

        return question

    # ── messages ─────────────────────────────────────────────

    def build_messages(
        self,
        system_prompt: str,
        question: str,
        history: list[dict] | None = None,
    ) -> list[dict]:
        """Build the messages list for the LLM."""
        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        # Inject history turns if history is enabled
        hist_cfg = self._cfg.get("history", {})
        if hist_cfg.get("enabled") and history:
            max_turns = hist_cfg.get("max_turns", 5)
            strategy = hist_cfg.get("strategy", "tail")
            turns = history[-max_turns:] if strategy == "tail" else history[:max_turns]
            messages.extend(turns)

        messages.append({"role": "user", "content": question})
        return messages

    # ── output ───────────────────────────────────────────────

    def validate_output(self, answer: str) -> str:
        out = self._cfg.get("output", {})

        if out.get("strip_whitespace", True):
            answer = answer.strip()

        if out.get("reject_empty", True) and not answer:
            raise ContextError("LLM returned an empty response.")

        min_len = out.get("min_length", 1)
        if len(answer) < min_len:
            raise ContextError(
                f"LLM response length {len(answer)} is below minimum {min_len}."
            )

        max_len = out.get("max_length", 16000)
        if len(answer) > max_len:
            answer = answer[:max_len]

        return answer

    # ── injection flags ──────────────────────────────────────

    @property
    def inject_date(self) -> bool:
        return self._cfg.get("injection", {}).get("current_date", True)

    @property
    def inject_agent_name(self) -> bool:
        return self._cfg.get("injection", {}).get("agent_name", True)


# ── helpers ──────────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


_HARD_DEFAULTS: dict[str, Any] = {
    "input": {"max_length": 4000, "strip_whitespace": True, "reject_empty": True},
    "injection": {"current_date": True, "agent_name": True, "task_id": True},
    "history": {"enabled": False, "max_turns": 5, "strategy": "tail"},
    "output": {"reject_empty": True, "min_length": 1, "strip_whitespace": True, "max_length": 16000},
}
