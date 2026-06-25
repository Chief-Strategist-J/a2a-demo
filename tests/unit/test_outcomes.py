"""Tests for shared/outcomes.py — OutcomeRecorder."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from shared.outcomes import OutcomeRecorder


class TestOutcomeRecorder:
    def test_creates_outcomes_dir(self, tmp_path):
        rec = OutcomeRecorder("worker", "groq/llama", outcomes_dir=tmp_path / "out")
        rec.record("t1", "question", "answer", 500)
        assert (tmp_path / "out").exists()

    def test_record_writes_jsonl(self, tmp_outcomes):
        rec = OutcomeRecorder("worker", "groq/llama", outcomes_dir=tmp_outcomes)
        rec.record("task-1", "What is AI?", "AI is...", 800)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = tmp_outcomes / f"{date_str}.jsonl"
        assert path.exists()
        lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1

    def test_record_fields(self, tmp_outcomes):
        rec = OutcomeRecorder("worker", "groq/llama", outcomes_dir=tmp_outcomes)
        rec.record("t1", "q", "a" * 50, 1200, tool_calls=["calculator"])
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entry = json.loads((tmp_outcomes / f"{date_str}.jsonl").read_text().strip())
        assert entry["agent"] == "worker"
        assert entry["task_id"] == "t1"
        assert entry["model"] == "groq/llama"
        assert entry["question_len"] == 1
        assert entry["answer_len"] == 50
        assert entry["latency_ms"] == 1200
        assert entry["tool_calls"] == ["calculator"]
        assert entry["error"] is None
        assert "ts" in entry

    def test_record_with_error(self, tmp_outcomes):
        rec = OutcomeRecorder("worker", "groq/llama", outcomes_dir=tmp_outcomes)
        rec.record("t2", "q", "", 0, error="LLM timeout")
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entry = json.loads((tmp_outcomes / f"{date_str}.jsonl").read_text().strip())
        assert entry["error"] == "LLM timeout"

    def test_multiple_records_appended(self, tmp_outcomes):
        rec = OutcomeRecorder("worker", "groq/llama", outcomes_dir=tmp_outcomes)
        rec.record("t1", "q1", "a1", 100)
        rec.record("t2", "q2", "a2", 200)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = (tmp_outcomes / f"{date_str}.jsonl").read_text().splitlines()
        assert len(lines) == 2

    def test_summary_no_records(self, tmp_outcomes):
        rec = OutcomeRecorder("worker", "groq/llama", outcomes_dir=tmp_outcomes)
        s = rec.summary("2000-01-01")
        assert s["total"] == 0

    def test_summary_calculates_stats(self, tmp_outcomes):
        rec = OutcomeRecorder("worker", "groq/llama", outcomes_dir=tmp_outcomes)
        rec.record("t1", "q", "a", 100)
        rec.record("t2", "q", "a", 300)
        rec.record("t3", "q", "", 0, error="fail")
        s = rec.summary()
        assert s["total"] == 3
        assert s["errors"] == 1
        assert s["avg_latency_ms"] == 133  # (100 + 300 + 0) / 3

    def test_summary_filters_by_agent(self, tmp_outcomes):
        rec_worker = OutcomeRecorder("worker", "groq/llama", outcomes_dir=tmp_outcomes)
        rec_planner = OutcomeRecorder("planner", "groq/llama", outcomes_dir=tmp_outcomes)
        rec_worker.record("t1", "q", "a", 100)
        rec_worker.record("t2", "q", "a", 200)
        rec_planner.record("t3", "q", "a", 500)
        # Each recorder only counts its own agent
        assert rec_worker.summary()["total"] == 2
        assert rec_planner.summary()["total"] == 1
