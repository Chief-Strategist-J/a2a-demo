"""Tests for shared/context.py — ContextManager validation and message building."""
from __future__ import annotations

from pathlib import Path

import pytest

from shared.context import ContextError, ContextManager

ROOT = Path(__file__).parent.parent.parent
CONTEXT_FILE = ROOT / "context.yaml"


class TestContextManagerLoad:
    def test_loads_real_context_file(self):
        managers = ContextManager.load(CONTEXT_FILE)
        assert "worker" in managers
        assert "planner" in managers

    def test_default_manager_returned(self):
        mgr = ContextManager.default()
        assert isinstance(mgr, ContextManager)


class TestInputValidation:
    def setup_method(self):
        self.mgr = ContextManager.load(CONTEXT_FILE)["worker"]

    def test_valid_question_passes(self):
        q = self.mgr.validate_input("What is Docker?")
        assert q == "What is Docker?"

    def test_strips_whitespace(self):
        q = self.mgr.validate_input("  hello  ")
        assert q == "hello"

    def test_empty_question_rejected(self):
        with pytest.raises(ContextError, match="empty"):
            self.mgr.validate_input("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(ContextError, match="empty"):
            self.mgr.validate_input("   \n\t  ")

    def test_question_at_max_length_passes(self):
        q = "x" * 4000
        result = self.mgr.validate_input(q)
        assert len(result) == 4000

    def test_question_exceeding_max_length_rejected(self):
        q = "x" * 4001
        with pytest.raises(ContextError, match="exceeds limit"):
            self.mgr.validate_input(q)


class TestOutputValidation:
    def setup_method(self):
        self.mgr = ContextManager.load(CONTEXT_FILE)["worker"]

    def test_valid_answer_passes(self):
        ans = self.mgr.validate_output("This is a good answer.")
        assert ans == "This is a good answer."

    def test_strips_whitespace_from_output(self):
        ans = self.mgr.validate_output("  answer  ")
        assert ans == "answer"

    def test_empty_output_rejected(self):
        with pytest.raises(ContextError, match="empty"):
            self.mgr.validate_output("")

    def test_whitespace_only_output_rejected(self):
        with pytest.raises(ContextError, match="empty"):
            self.mgr.validate_output("   ")

    def test_long_output_truncated(self):
        long_answer = "a" * 20000
        result = self.mgr.validate_output(long_answer)
        assert len(result) <= 16000


class TestMessageBuilding:
    def setup_method(self):
        self.mgr = ContextManager.default()

    def test_messages_include_system_and_user(self):
        msgs = self.mgr.build_messages("You are helpful.", "What is AI?")
        roles = [m["role"] for m in msgs]
        assert "system" in roles
        assert "user" in roles

    def test_system_message_first(self):
        msgs = self.mgr.build_messages("System.", "Question.")
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "System."

    def test_user_message_last(self):
        msgs = self.mgr.build_messages("System.", "Question.")
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "Question."

    def test_history_not_injected_when_disabled(self):
        history = [
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
        ]
        msgs = self.mgr.build_messages("System.", "New question.", history=history)
        # Stateless — history should NOT appear
        roles = [m["role"] for m in msgs]
        assert roles.count("user") == 1
