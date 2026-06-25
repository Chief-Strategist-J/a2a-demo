"""Worker Agent — A2A config-driven implementation.

Reads config.yaml, builds a LangGraph graph from the YAML flow definition,
and exposes:
  GET  /.well-known/agent.json   — A2A Agent Card (public)
  GET  /health                   — liveness (public)
  POST /                         — A2A JSON-RPC 2.0 endpoint (auth required)
                                   supports tasks/send (sync)
                                   and tasks/sendSubscribe (SSE stream)

Adding a tool
-------------
1. Create  shared/tools/<name>.py  with @register(...)
2. Import it in this file (see "register tools" block below)
3. Set enabled: true in config.yaml under worker.tools
"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

sys.path.insert(0, str(Path(__file__).parent.parent))

if "pytest" not in sys.modules:
    load_dotenv(Path(__file__).parent.parent / ".env")

from shared import config as cfg_mod
from shared import prompts as prompt_lib
from shared.auth import BearerAuthMiddleware
from shared.context import ContextManager
from shared.graph_builder import AgentState, build_graph
from shared.model_factory import build_chain
from shared.outcomes import OutcomeRecorder

import shared.tools.calculator
import shared.tools.web_search


_ROOT = Path(__file__).parent.parent
_CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", _ROOT / "config.yaml"))
_PROMPTS_PATH = Path(os.environ.get("PROMPTS_PATH", _ROOT / "prompts.yaml"))
_CONTEXT_PATH = Path(os.environ.get("CONTEXT_PATH", _ROOT / "context.yaml"))

cfg = cfg_mod.load(_CONFIG_PATH)
agent_cfg = cfg.agents["worker"]
_model_chain = build_chain(agent_cfg.model_chain, cfg.models, cfg.providers)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [worker]  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("worker")


if _PROMPTS_PATH.exists():
    prompt_lib.load(_PROMPTS_PATH)
    log.info("Loaded %d prompts from %s", len(prompt_lib.list_prompts()), _PROMPTS_PATH)

_ctx_managers = (
    ContextManager.load(_CONTEXT_PATH) if _CONTEXT_PATH.exists() else {}
)
_ctx = _ctx_managers.get("worker") or ContextManager.default()
_recorder = OutcomeRecorder(
    agent="worker",
    model=_model_chain.primary_label,
)


graph = build_graph(
    flow_cfg=agent_cfg.flow.model_dump(),
    model_chain=_model_chain,
    tool_cfgs=[t.model_dump() for t in agent_cfg.tools],
    agent_endpoints={},
    agent_name=agent_cfg.name,
    ctx_mgr=_ctx,
    recorder=_recorder,
    outbound_token="",
)


app = FastAPI(title=agent_cfg.name, version="2.0.0")

if cfg.auth.enabled:
    app.add_middleware(
        BearerAuthMiddleware,
        valid_tokens=set(cfg.auth.tokens.values()),
    )


_AGENT_CARD = {
    "name": agent_cfg.name,
    "description": agent_cfg.description,
    "url": agent_cfg.public_url,
    "version": "2.0.0",
    "capabilities": {
        "streaming": cfg.streaming.enabled,
        "pushNotifications": False,
    },
    "skills": [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "inputModes": s.input_modes,
            "outputModes": s.output_modes,
        }
        for s in agent_cfg.skills
    ],
}


@app.get("/.well-known/agent.json")
async def agent_card():
    return _AGENT_CARD


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "agent": agent_cfg.name,
        "model_chain": _model_chain.chain_labels,
    }



@app.post("/")
async def a2a(request: Request):
    body: dict = await request.json()
    jsonrpc_id = body.get("id")
    method: str = body.get("method", "")
    params: dict = body.get("params", {})
    accept: str = request.headers.get("Accept", "")

    want_stream = "text/event-stream" in accept or method == "tasks/sendSubscribe"

    log.info("═" * 60)
    log.info("[A2A]  method='%s'  id=%s  stream=%s", method, jsonrpc_id, want_stream)

    if method not in ("tasks/send", "tasks/sendSubscribe"):
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": jsonrpc_id,
            "error": {"code": -32601, "message": f"Method not supported: '{method}'"},
        }, status_code=400)

    task_id: str = params.get("id") or str(uuid.uuid4())
    parts: list = params.get("message", {}).get("parts", [])
    question: str = next((p["text"] for p in parts if p.get("type") == "text"), "")

    if want_stream:
        return StreamingResponse(
            _stream_task(task_id, question, jsonrpc_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    final: AgentState = await graph.ainvoke(
        {"task_id": task_id, "question": question, "answer": "", "tool_results": []}
    )

    log.info("[A2A]  task %s completed (%d chars)", task_id, len(final["answer"]))
    return JSONResponse(_completed_response(jsonrpc_id, task_id, final["answer"]))


def _completed_response(jsonrpc_id: str, task_id: str, answer: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": jsonrpc_id,
        "result": {
            "id": task_id,
            "status": {
                "state": "completed",
                "message": {
                    "role": "agent",
                    "parts": [{"type": "text", "text": answer}],
                },
            },
            "artifacts": [],
        },
    }


def _sse(data: dict) -> bytes:
    return f"data: {json.dumps(data)}\n\n".encode()


async def _stream_task(
    task_id: str, question: str, jsonrpc_id: str
) -> AsyncIterator[bytes]:
    """Run the LangGraph graph and emit A2A SSE events."""

    yield _sse({
        "jsonrpc": "2.0",
        "id": jsonrpc_id,
        "result": {
            "id": task_id,
            "status": {"state": "working"},
            "final": False,
        },
    })

    final_answer = ""

    try:
        async for mode, chunk in graph.astream(
            {"task_id": task_id, "question": question, "answer": "", "tool_results": []},
            stream_mode=["updates", "values"],
        ):
            if mode == "values" and chunk.get("answer"):
                final_answer = chunk["answer"]
                yield _sse({
                    "jsonrpc": "2.0",
                    "id": jsonrpc_id,
                    "result": {
                        "id": task_id,
                        "artifact": {
                            "parts": [{"type": "text", "text": final_answer}],
                            "index": 0,
                            "append": False,
                        },
                        "final": False,
                    },
                })

        log.info("[A2A stream]  task %s completed (%d chars)", task_id, len(final_answer))
        yield _sse({
            "jsonrpc": "2.0",
            "id": jsonrpc_id,
            "result": {
                "id": task_id,
                "status": {
                    "state": "completed",
                    "message": {
                        "role": "agent",
                        "parts": [{"type": "text", "text": final_answer}],
                    },
                },
                "final": True,
            },
        })

    except Exception as exc:
        log.error("[A2A stream]  task %s failed: %s", task_id, exc, exc_info=True)
        yield _sse({
            "jsonrpc": "2.0",
            "id": jsonrpc_id,
            "result": {
                "id": task_id,
                "status": {"state": "failed"},
                "final": True,
            },
        })
        yield _sse({
            "jsonrpc": "2.0",
            "id": jsonrpc_id,
            "error": {"code": -32000, "message": str(exc)},
        })


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=agent_cfg.port, reload=True)
