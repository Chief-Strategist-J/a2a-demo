"""Config-driven LangGraph builder.

Reads the `flow` section of config.yaml and constructs a compiled StateGraph.
Integrates prompts.py, context.py, and outcomes.py for every LLM call.

Node types
----------
passthrough   — log and pass state through unchanged
llm_call      — call the configured LLM with prompt + context management
a2a_delegate  — send an A2A task to another agent (streaming or sync)

Adding a new node type
----------------------
1. Write a factory  _make_<type>(node_id, ...) -> async callable
2. Add a branch in build_graph()
3. Declare in config.yaml with  type: <type>

Testability
-----------
build_graph() accepts an optional llm_client parameter. Pass a mock
AsyncOpenAI-compatible object in tests to avoid real API calls.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, TypedDict

import httpx
from langgraph.graph import END, StateGraph
from openai import AsyncOpenAI

from shared import prompts as prompt_lib
from shared.context import ContextError, ContextManager
from shared.model_factory import build_client
from shared.outcomes import OutcomeRecorder
from shared.tools.registry import Tool, get_enabled

log = logging.getLogger(__name__)


# ── shared agent state ───────────────────────────────────────

class AgentState(TypedDict):
    task_id: str
    question: str
    answer: str
    tool_results: list[dict]


# ── node factories ────────────────────────────────────────────

def _make_passthrough(node_id: str):
    async def _node(state: AgentState) -> dict:
        log.info(
            "[node: %s]  task_id=%s  q='%.60s'",
            node_id,
            state.get("task_id") or "-",
            state.get("question", ""),
        )
        return {}

    _node.__name__ = node_id
    return _node


def _make_llm_call(
    node_id: str,
    model_cfg: dict,
    provider_cfg: dict,
    node_cfg: dict,
    tool_cfgs: list[dict],
    agent_name: str,
    ctx_mgr: ContextManager,
    recorder: OutcomeRecorder,
    llm_client: AsyncOpenAI | None = None,
):
    client: AsyncOpenAI = llm_client or build_client(model_cfg["provider"], provider_cfg)
    use_tools: bool = node_cfg.get("use_tools", False)
    prompt_id: str | None = node_cfg.get("prompt_id")
    inline_prompt: str = node_cfg.get("system_prompt", "You are a helpful assistant.")

    enabled_tools: list[Tool] = get_enabled(tool_cfgs) if use_tools else []
    tool_schemas = [t.openai_schema() for t in enabled_tools]
    tool_map: dict[str, Tool] = {t.name: t for t in enabled_tools}

    async def _node(state: AgentState) -> dict:
        task_id = state.get("task_id") or str(uuid.uuid4())
        log.info(
            "[node: %s]  task_id=%s  model=%s/%s  tools=%s",
            node_id,
            task_id,
            model_cfg["provider"],
            model_cfg["model_id"],
            [t.name for t in enabled_tools] or "none",
        )

        # ── 1. validate input ─────────────────────────────────
        try:
            question = ctx_mgr.validate_input(state.get("question", ""))
        except ContextError as exc:
            log.warning("[node: %s]  input rejected: %s", node_id, exc)
            recorder.record(task_id, "", "", 0, error=str(exc))
            return {"answer": f"[input error] {exc}"}

        # ── 2. resolve system prompt ──────────────────────────
        try:
            if prompt_id and prompt_lib.is_loaded():
                system_prompt = prompt_lib.render(
                    prompt_id, prompt_lib.standard_vars(agent_name)
                )
            else:
                system_prompt = inline_prompt
        except KeyError as exc:
            log.error("[node: %s]  prompt error: %s", node_id, exc)
            system_prompt = inline_prompt

        # ── 3. build messages ─────────────────────────────────
        messages = ctx_mgr.build_messages(system_prompt, question)

        create_kwargs: dict[str, Any] = dict(
            model=model_cfg["model_id"],
            messages=messages,
            temperature=model_cfg.get("temperature", 0.1),
            max_tokens=model_cfg.get("max_tokens", 1024),
        )
        if tool_schemas:
            create_kwargs["tools"] = tool_schemas
            create_kwargs["tool_choice"] = "auto"

        t_start = time.monotonic()
        tool_calls_used: list[str] = []

        # ── 4. call LLM ───────────────────────────────────────
        try:
            response = await client.chat.completions.create(**create_kwargs)
        except Exception as exc:
            latency = int((time.monotonic() - t_start) * 1000)
            log.error("[node: %s]  LLM call failed: %s", node_id, exc)
            recorder.record(task_id, question, "", latency, error=str(exc))
            return {"answer": f"[llm error] The AI call failed: {exc}"}

        if not response.choices:
            recorder.record(task_id, question, "", 0, error="empty choices")
            return {"answer": "[llm error] Empty response from model."}

        msg = response.choices[0].message

        # ── 5. handle tool calls ──────────────────────────────
        if msg.tool_calls and tool_map:
            messages.append(msg)
            tool_results: list[dict] = list(state.get("tool_results") or [])

            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError as exc:
                    log.error("[tool: %s]  bad args JSON: %s", tc.function.name, exc)
                    args = {}

                tool = tool_map.get(tc.function.name)
                result = tool.run(**args) if tool else f"Tool '{tc.function.name}' not found."
                log.info("[tool: %s]  %s → %s", tc.function.name, args, result)
                tool_calls_used.append(tc.function.name)
                tool_results.append({"tool": tc.function.name, "args": args, "result": result})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

            try:
                follow = await client.chat.completions.create(
                    model=model_cfg["model_id"],
                    messages=messages,
                    temperature=model_cfg.get("temperature", 0.1),
                    max_tokens=model_cfg.get("max_tokens", 1024),
                )
            except Exception as exc:
                latency = int((time.monotonic() - t_start) * 1000)
                log.error("[node: %s]  tool follow-up LLM call failed: %s", node_id, exc)
                recorder.record(task_id, question, "", latency, tool_calls_used, str(exc))
                return {"answer": f"[llm error] Tool follow-up failed: {exc}"}

            raw_answer = (
                follow.choices[0].message.content if follow.choices else ""
            ) or ""
        else:
            raw_answer = msg.content or ""

        # ── 6. validate output ────────────────────────────────
        try:
            answer = ctx_mgr.validate_output(raw_answer)
        except ContextError as exc:
            log.warning("[node: %s]  output rejected: %s", node_id, exc)
            recorder.record(task_id, question, raw_answer, 0, tool_calls_used, str(exc))
            return {"answer": f"[output error] {exc}"}

        latency = int((time.monotonic() - t_start) * 1000)
        log.info("[node: %s]  done  latency=%dms  answer_len=%d", node_id, latency, len(answer))
        recorder.record(task_id, question, answer, latency, tool_calls_used)

        result_state: dict[str, Any] = {"answer": answer}
        if tool_calls_used:
            result_state["tool_results"] = tool_results  # type: ignore[assignment]
        return result_state

    _node.__name__ = node_id
    return _node


def _make_a2a_delegate(
    node_id: str,
    node_cfg: dict,
    agent_endpoints: dict,
    outbound_token: str,
):
    target_key: str = node_cfg.get("target_agent", "")
    worker_url: str = agent_endpoints.get(target_key, {}).get("url", "http://localhost:8001")
    do_stream: bool = node_cfg.get("streaming", True)
    auth_headers: dict[str, str] = (
        {"Authorization": f"Bearer {outbound_token}"} if outbound_token else {}
    )

    async def _node(state: AgentState) -> dict:
        task_id = state.get("task_id") or str(uuid.uuid4())
        question = state.get("question", "")

        if not question.strip():
            log.warning("[node: %s]  empty question — skipping A2A call", node_id)
            return {"answer": "[delegate error] Empty question."}

        # Discover worker via Agent Card
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                card_resp = await client.get(f"{worker_url}/.well-known/agent.json")
                card_resp.raise_for_status()
                agent_name = card_resp.json().get("name", target_key)
        except Exception as exc:
            log.error("[node: %s]  agent card fetch failed for '%s': %s", node_id, target_key, exc)
            return {"answer": f"[delegate error] Could not reach agent '{target_key}': {exc}"}

        log.info(
            "[node: %s]  → A2A '%s'  url=%s  stream=%s",
            node_id, agent_name, worker_url, do_stream,
        )

        method = "tasks/sendSubscribe" if do_stream else "tasks/send"
        payload = {
            "jsonrpc": "2.0",
            "id": f"req-{task_id}",
            "method": method,
            "params": {
                "id": task_id,
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": question}],
                },
            },
        }

        try:
            if do_stream:
                answer = await _consume_sse(worker_url, payload, auth_headers)
            else:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{worker_url}/", json=payload, headers=auth_headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if "error" in data:
                        raise RuntimeError(f"Worker returned error: {data['error']}")
                    answer = data["result"]["status"]["message"]["parts"][0]["text"]
        except Exception as exc:
            log.error("[node: %s]  A2A call to '%s' failed: %s", node_id, agent_name, exc)
            return {"answer": f"[delegate error] A2A call to '{agent_name}' failed: {exc}"}

        if not answer.strip():
            log.warning("[node: %s]  worker returned empty answer", node_id)
            return {"answer": "[delegate error] Worker returned an empty answer."}

        log.info("[node: %s]  ← %d chars from '%s'", node_id, len(answer), agent_name)
        return {"answer": answer}

    _node.__name__ = node_id
    return _node


async def _consume_sse(url: str, payload: dict, headers: dict) -> str:
    """Consume a tasks/sendSubscribe SSE stream and return the final answer."""
    final_answer = ""
    sse_headers = {**headers, "Accept": "text/event-stream"}

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", f"{url}/", json=payload, headers=sse_headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    log.debug("[sse]  skipping non-JSON line: %.80s", raw)
                    continue

                result = event.get("result", {})
                if "status" in result:
                    status = result["status"]
                    if status.get("state") == "completed":
                        parts = status.get("message", {}).get("parts", [])
                        for p in parts:
                            if p.get("type") == "text":
                                final_answer = p.get("text", "")
                elif "artifact" in result:
                    for p in result["artifact"].get("parts", []):
                        if p.get("type") == "text":
                            txt = p.get("text", "")
                            final_answer = (final_answer + txt) if result["artifact"].get("append") else txt

    return final_answer


# ── public API ────────────────────────────────────────────────

def build_graph(
    flow_cfg: dict,
    model_cfg: dict,
    provider_cfg: dict,
    tool_cfgs: list[dict],
    agent_endpoints: dict,
    agent_name: str = "Agent",
    ctx_mgr: ContextManager | None = None,
    recorder: OutcomeRecorder | None = None,
    outbound_token: str = "",
    llm_client: AsyncOpenAI | None = None,
) -> Any:
    """Build and compile a LangGraph StateGraph from the config.yaml flow section.

    Parameters
    ----------
    llm_client:
        Optional pre-built AsyncOpenAI client. When provided, it is used
        instead of calling build_client() — useful in tests.
    ctx_mgr:
        Optional ContextManager. Defaults to ContextManager.default().
    recorder:
        Optional OutcomeRecorder. Defaults to a recorder that logs to outcomes/.
    """
    _ctx = ctx_mgr or ContextManager.default()
    _rec = recorder or OutcomeRecorder(
        agent=agent_name,
        model=f"{model_cfg['provider']}/{model_cfg['model_id']}",
    )

    builder = StateGraph(AgentState)

    for node in flow_cfg["nodes"]:
        nid: str = node["id"]
        ntype: str = node["type"]
        ncfg: dict = node.get("config", {})

        if ntype == "passthrough":
            builder.add_node(nid, _make_passthrough(nid))

        elif ntype == "llm_call":
            builder.add_node(
                nid,
                _make_llm_call(
                    nid, model_cfg, provider_cfg, ncfg, tool_cfgs,
                    agent_name, _ctx, _rec, llm_client,
                ),
            )

        elif ntype == "a2a_delegate":
            builder.add_node(
                nid,
                _make_a2a_delegate(nid, ncfg, agent_endpoints, outbound_token),
            )

        else:
            raise ValueError(
                f"Unknown node type '{ntype}' for node '{nid}'. "
                "Supported: passthrough, llm_call, a2a_delegate"
            )

    builder.set_entry_point(flow_cfg["entry"])

    nodes_with_out = {e[0] for e in flow_cfg["edges"]}
    for edge in flow_cfg["edges"]:
        builder.add_edge(edge[0], edge[1])

    # Leaf nodes auto-connect to END
    all_node_ids = {n["id"] for n in flow_cfg["nodes"]}
    for nid in all_node_ids - nodes_with_out:
        builder.add_edge(nid, END)

    return builder.compile()
