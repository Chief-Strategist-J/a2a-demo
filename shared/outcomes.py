"""Outcome recorder — writes every task result to a JSONL file.

Each line in outcomes/YYYY-MM-DD.jsonl is one completed task:
  {
    "ts": "2026-06-25T14:30:00.123Z",
    "agent": "worker",
    "task_id": "abc-123",
    "model": "groq/llama-3.1-8b-instant",
    "question_len": 42,
    "answer_len": 310,
    "latency_ms": 1240,
    "tool_calls": ["calculator"],
    "error": null
  }

Usage:
    from shared.outcomes import OutcomeRecorder
    rec = OutcomeRecorder(agent="worker", model="groq/llama-3.1-8b-instant")
    rec.record(task_id, question, answer, latency_ms, tool_calls)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_OUTCOMES_DIR = Path("outcomes")


class OutcomeRecorder:
    def __init__(
        self,
        agent: str,
        model: str,
        outcomes_dir: Path | str = _OUTCOMES_DIR,
    ) -> None:
        self._agent = agent
        self._model = model
        self._dir = Path(outcomes_dir)

    def record(
        self,
        task_id: str,
        question: str,
        answer: str,
        latency_ms: int,
        tool_calls: list[str] | None = None,
        error: str | None = None,
    ) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": self._agent,
            "task_id": task_id,
            "model": self._model,
            "question_len": len(question),
            "answer_len": len(answer),
            "latency_ms": latency_ms,
            "tool_calls": tool_calls or [],
            "error": error,
        }
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            path = self._dir / f"{date_str}.jsonl"
            with open(path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as exc:
            log.warning("Could not write outcome record: %s", exc)

    def summary(self, date_str: str | None = None) -> dict:
        """Return aggregate stats for a given day (default: today)."""
        date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self._dir / f"{date_str}.jsonl"
        if not path.exists():
            return {"date": date_str, "total": 0}

        records: list[dict] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        if not records:
            return {"date": date_str, "total": 0}

        agent_records = [r for r in records if r.get("agent") == self._agent]
        errors = [r for r in agent_records if r.get("error")]
        latencies = [r["latency_ms"] for r in agent_records if "latency_ms" in r]
        tool_uses = [r for r in agent_records if r.get("tool_calls")]

        return {
            "date": date_str,
            "agent": self._agent,
            "total": len(agent_records),
            "errors": len(errors),
            "tool_uses": len(tool_uses),
            "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
            "p95_latency_ms": int(sorted(latencies)[int(len(latencies) * 0.95)]) if latencies else 0,
            "avg_answer_len": int(
                sum(r["answer_len"] for r in agent_records) / len(agent_records)
            ),
        }
