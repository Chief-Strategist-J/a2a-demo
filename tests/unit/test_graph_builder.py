"""Tests for shared/graph_builder.py — graph construction and node behaviour."""
from __future__ import annotations

import pytest
from pathlib import Path
from tests.conftest import make_mock_llm, make_mock_llm_with_tool

from shared.config import load
from shared.context import ContextManager
from shared.graph_builder import AgentState, build_graph
from shared.model_factory import ModelChain
from shared.outcomes import OutcomeRecorder
import shared.tools.calculator
import shared.tools.web_search

ROOT = Path(__file__).parent.parent.parent
cfg = load(ROOT / "config.yaml")


def _worker_graph(mock_client=None, ctx=None, rec=None):
    agent_cfg = cfg.agents["worker"]
    return build_graph(
        flow_cfg=agent_cfg.flow.model_dump(),
        model_chain=ModelChain.from_mock(mock_client or make_mock_llm()),
        tool_cfgs=[t.model_dump() for t in agent_cfg.tools],
        agent_endpoints={},
        agent_name=agent_cfg.name,
        ctx_mgr=ctx or ContextManager.default(),
        recorder=rec or OutcomeRecorder("worker", "test/model", outcomes_dir="/tmp/test_outcomes"),
    )


class TestGraphConstruction:
    def test_worker_graph_builds(self):
        g = _worker_graph(make_mock_llm())
        assert g is not None

    def test_worker_nodes_present(self):
        g = _worker_graph(make_mock_llm())
        node_keys = list(g.nodes.keys())
        assert "receive_task" in node_keys
        assert "call_ai" in node_keys
        assert "format_response" in node_keys

    def test_unknown_node_type_raises(self, tmp_path):
        bad_flow = {
            "entry": "n1",
            "nodes": [{"id": "n1", "type": "totally_unknown_type"}],
            "edges": [],
        }
        with pytest.raises(ValueError, match="Unknown node type"):
            build_graph(
                flow_cfg=bad_flow,
                model_chain=ModelChain.from_mock(make_mock_llm()),
                tool_cfgs=[],
                agent_endpoints={},
            )

    def test_llm_call_without_chain_raises(self):
        flow = {
            "entry": "n1",
            "nodes": [{"id": "n1", "type": "llm_call", "config": {}}],
            "edges": [],
        }
        with pytest.raises(ValueError, match="no model_chain"):
            build_graph(flow_cfg=flow, model_chain=None, tool_cfgs=[], agent_endpoints={})


@pytest.mark.asyncio
class TestLLMCallNode:
    async def test_returns_mock_answer(self):
        g = _worker_graph(make_mock_llm("Mocked answer here."))
        state: AgentState = await g.ainvoke({
            "task_id": "test-1", "question": "What is Python?",
            "answer": "", "tool_results": [],
        })
        assert state["answer"] == "Mocked answer here."

    async def test_empty_question_returns_error(self):
        g = _worker_graph(make_mock_llm())
        state = await g.ainvoke({
            "task_id": "t2", "question": "",
            "answer": "", "tool_results": [],
        })
        assert "[input error]" in state["answer"] or state["answer"] == ""

    async def test_whitespace_only_question_returns_error(self):
        g = _worker_graph(make_mock_llm())
        state = await g.ainvoke({
            "task_id": "t3", "question": "   ",
            "answer": "", "tool_results": [],
        })
        assert "[input error]" in state["answer"] or state["answer"] == ""

    async def test_records_outcome(self, tmp_outcomes):
        from datetime import datetime, timezone
        import json
        rec = OutcomeRecorder("worker", "test/model", outcomes_dir=tmp_outcomes)
        g = _worker_graph(make_mock_llm("Answer"), rec=rec)
        await g.ainvoke({
            "task_id": "t-rec", "question": "test?",
            "answer": "", "tool_results": [],
        })
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = (tmp_outcomes / f"{date_str}.jsonl").read_text().splitlines()
        assert len(lines) >= 1
        entry = json.loads(lines[0])
        assert entry["agent"] == "worker"


@pytest.mark.asyncio
class TestToolCallNode:
    async def test_tool_call_round_trip(self):
        mock = make_mock_llm_with_tool(
            tool_name="calculator",
            tool_args={"expression": "2 + 2"},
            follow_up_answer="The answer is 4.",
        )
        agent_cfg = cfg.agents["worker"]
        tool_cfgs = [
            {"name": "calculator", "enabled": True, "description": "math"},
            {"name": "web_search", "enabled": False, "description": "search"},
        ]
        g = build_graph(
            flow_cfg=agent_cfg.flow.model_dump(),
            model_chain=ModelChain.from_mock(mock),
            tool_cfgs=tool_cfgs,
            agent_endpoints={},
            agent_name=agent_cfg.name,
            ctx_mgr=ContextManager.default(),
            recorder=OutcomeRecorder("worker", "t", outcomes_dir="/tmp/test_outcomes"),
        )
        state = await g.ainvoke({
            "task_id": "tool-1", "question": "What is 2 + 2?",
            "answer": "", "tool_results": [],
        })
        assert "4" in state["answer"]
