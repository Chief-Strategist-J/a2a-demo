from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

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
agent_cfg = cfg.agents["planner"]
_model_chain = build_chain(agent_cfg.model_chain, cfg.models, cfg.providers)

_OUTBOUND_TOKEN = cfg.auth.tokens.get("planner", "") if cfg.auth.enabled else ""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [planner]  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("planner")

if _PROMPTS_PATH.exists():
    prompt_lib.load(_PROMPTS_PATH)

_ctx_managers = ContextManager.load(_CONTEXT_PATH) if _CONTEXT_PATH.exists() else {}
_ctx = _ctx_managers.get("planner") or ContextManager.default()
_recorder = OutcomeRecorder(agent="planner", model=_model_chain.primary_label)

graph = build_graph(
    flow_cfg=agent_cfg.flow.model_dump(),
    model_chain=_model_chain,
    tool_cfgs=[t.model_dump() for t in agent_cfg.tools],
    agent_endpoints={k: v.model_dump() for k, v in cfg.agent_endpoints.items()},
    agent_name=agent_cfg.name,
    ctx_mgr=_ctx,
    recorder=_recorder,
    outbound_token=_OUTBOUND_TOKEN,
)

app = FastAPI(title=agent_cfg.name, version="2.0.0")

if cfg.auth.enabled:
    app.add_middleware(BearerAuthMiddleware, valid_tokens=set(cfg.auth.tokens.values()))

_AGENT_CARD = {
    "name": agent_cfg.name,
    "description": agent_cfg.description,
    "url": agent_cfg.public_url,
    "version": "2.0.0",
    "capabilities": {"streaming": cfg.streaming.enabled, "pushNotifications": False},
    "skills": [
        {"id": s.id, "name": s.name, "description": s.description,
         "inputModes": s.input_modes, "outputModes": s.output_modes}
        for s in agent_cfg.skills
    ],
}


@app.get("/.well-known/agent.json")
async def agent_card():
    return _AGENT_CARD


@app.get("/health")
async def health():
    return {"status": "ok", "agent": agent_cfg.name, "model_chain": _model_chain.chain_labels}


class Question(BaseModel):
    question: str


@app.post("/ask")
async def ask(body: Question):
    log.info("═" * 60)
    log.info("[/ask]  question='%s'", body.question)
    final: AgentState = await graph.ainvoke(
        {"task_id": "", "question": body.question, "answer": "", "tool_results": []}
    )
    return {"question": body.question, "answer": final["answer"]}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=agent_cfg.port, reload=True)
