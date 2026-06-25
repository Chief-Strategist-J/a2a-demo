"""Shared pytest fixtures.

The mock_llm_client fixture returns an AsyncOpenAI-compatible mock that
returns a deterministic response without making real API calls.
Pass it to build_graph(llm_client=...) in tests.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("CONFIG_PATH", str(ROOT / "config.yaml"))
os.environ.setdefault("PROMPTS_PATH", str(ROOT / "prompts.yaml"))
os.environ.setdefault("CONTEXT_PATH", str(ROOT / "context.yaml"))

os.environ.setdefault("GEMINI_API_KEY", "_test_key_gemini")
os.environ.setdefault("GROQ_API_KEY", "_test_key_groq")
os.environ.setdefault("OPENROUTER_API_KEY", "_test_key_openrouter")


def make_mock_llm(answer: str = "This is a mock answer.") -> MagicMock:
    """Return a mock AsyncOpenAI client that returns `answer` for any completion call."""
    mock_message = MagicMock()
    mock_message.content = answer
    mock_message.tool_calls = None

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=mock_response)
    return client


def make_mock_llm_with_tool(
    tool_name: str,
    tool_args: dict,
    follow_up_answer: str = "The result is 42.",
) -> MagicMock:
    """Return a mock that makes one tool call then answers."""
    import json

    tc = MagicMock()
    tc.id = "call_abc"
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(tool_args)

    first_msg = MagicMock()
    first_msg.content = None
    first_msg.tool_calls = [tc]

    first_resp = MagicMock()
    first_resp.choices = [MagicMock(message=first_msg)]

    second_msg = MagicMock()
    second_msg.content = follow_up_answer
    second_msg.tool_calls = None

    second_resp = MagicMock()
    second_resp.choices = [MagicMock(message=second_msg)]

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=[first_resp, second_resp])
    return client


@pytest.fixture
def mock_llm() -> MagicMock:
    return make_mock_llm()


@pytest.fixture
def tmp_outcomes(tmp_path: Path) -> Path:
    """A temporary outcomes directory, cleaned up after each test."""
    d = tmp_path / "outcomes"
    d.mkdir()
    return d
