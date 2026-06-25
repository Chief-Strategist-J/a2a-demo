from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
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


@app.get("/ui/stream")
async def ui_stream(question: str):
    async def _gen() -> AsyncIterator[bytes]:
        async for mode, chunk in graph.astream(
            {"task_id": "", "question": question, "answer": "", "tool_results": []},
            stream_mode=["updates", "values"],
        ):
            yield f"event: {mode}\ndata: {json.dumps(chunk)}\n\n".encode()
    return StreamingResponse(_gen(), media_type="text/event-stream")


@app.get("/ui", response_class=HTMLResponse)
async def trace_ui():
    return _build_ui()


def _build_ui() -> str:
    nodes = [n.id for n in agent_cfg.flow.nodes]
    node_types = {n.id: n.type for n in agent_cfg.flow.nodes}
    nodes_js = json.dumps(nodes)
    node_types_js = json.dumps(node_types)
    chain_label = " → ".join(_model_chain.chain_labels)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>A2A Trace — {agent_cfg.name}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Courier New',monospace;background:#0d1117;color:#c9d1d9;min-height:100vh;padding:32px}}
h1{{color:#58a6ff;font-size:1.4rem;margin-bottom:6px}}
.sub{{color:#8b949e;font-size:.8rem;margin-bottom:20px}}
.meta{{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:10px 16px;margin-bottom:24px;font-size:.78rem;color:#8b949e;display:flex;gap:24px;flex-wrap:wrap}}
.meta span{{color:#58a6ff}}
.row{{display:flex;gap:10px;margin-bottom:28px}}
input{{flex:1;background:#161b22;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:10px 14px;font-family:inherit;font-size:.95rem;outline:none}}
input:focus{{border-color:#58a6ff}}
button{{background:#238636;border:none;border-radius:6px;color:#fff;cursor:pointer;font-family:inherit;font-size:.95rem;padding:10px 22px}}
button:hover{{background:#2ea043}}
button:disabled{{background:#3d444d;cursor:default}}
.flow{{display:flex;align-items:center;flex-wrap:wrap;gap:0;margin-bottom:28px}}
.node{{background:#161b22;border:2px solid #30363d;border-radius:10px;padding:12px 18px;min-width:160px;text-align:center;transition:all .3s;margin:4px}}
.node .lbl{{font-size:.65rem;color:#8b949e;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px}}
.node .nm{{font-size:.9rem;color:#c9d1d9}}
.node .tp{{font-size:.65rem;color:#444d56;margin-top:2px}}
.node.active{{border-color:#f0883e;box-shadow:0 0 18px rgba(240,136,62,.4)}}
.node.active .nm{{color:#f0883e}}
.node.done{{border-color:#238636}}
.node.done .nm{{color:#3fb950}}
.arr{{color:#30363d;font-size:1.4rem;padding:0 4px;flex-shrink:0}}
.arr.active{{color:#3fb950}}
.sec{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:14px}}
.sec h2{{color:#8b949e;font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}}
.line{{font-size:.8rem;padding:2px 0;border-bottom:1px solid #1c2128}}
.line:last-child{{border-bottom:none}}
.tag{{display:inline-block;border-radius:4px;padding:1px 6px;font-size:.7rem;margin-right:5px}}
.tag.nd{{background:#1c2d3a;color:#58a6ff}}
.tag.a2{{background:#2d1c3a;color:#d2a8ff}}
.tag.dt{{background:#1c2b20;color:#3fb950}}
.tag.er{{background:#3a1c1c;color:#f85149}}
.answer{{background:#0d1117;border:1px solid #238636;border-radius:6px;padding:14px;white-space:pre-wrap;font-size:.9rem;line-height:1.6;color:#c9d1d9}}
.hidden{{display:none}}
</style>
</head>
<body>
<h1>A2A Trace Viewer</h1>
<p class="sub">Real-time LangGraph + A2A execution trace</p>
<div class="meta">
  <div>Agent: <span>{agent_cfg.name}</span></div>
  <div>Model chain: <span>{chain_label}</span></div>
  <div>Nodes: <span>{len(agent_cfg.flow.nodes)}</span></div>
  <div>Auth: <span>{'enabled' if cfg.auth.enabled else 'disabled'}</span></div>
  <div>Streaming: <span>{'enabled' if cfg.streaming.enabled else 'disabled'}</span></div>
</div>
<div class="row">
  <input type="text" id="q" placeholder="Ask anything…" value="What is Docker?" />
  <button id="btn" onclick="run()">Run</button>
</div>
<div class="flow" id="flow"></div>
<div class="sec">
  <h2>Execution log</h2>
  <div id="log"><span style="color:#8b949e;font-size:.8rem">Waiting for run…</span></div>
</div>
<div class="sec hidden" id="ans-sec">
  <h2>Answer</h2>
  <div class="answer" id="ans"></div>
</div>
<script>
const NODES={nodes_js};
const TYPES={node_types_js};
(function buildFlow(){{
  const c=document.getElementById("flow");
  NODES.forEach((n,i)=>{{
    const d=document.createElement("div");
    d.className="node";d.id="n-"+n;
    d.innerHTML=`<div class="lbl">node ${{i+1}}</div><div class="nm">${{n}}</div><div class="tp">${{TYPES[n]||""}}</div>`;
    c.appendChild(d);
    if(i<NODES.length-1){{const a=document.createElement("div");a.className="arr";a.id="a"+i;a.textContent="→";c.appendChild(a);}}
  }});
}})();
function reset(){{
  NODES.forEach(n=>{{document.getElementById("n-"+n).className="node";}});
  for(let i=0;i<NODES.length-1;i++)document.getElementById("a"+i).className="arr";
  document.getElementById("log").innerHTML="";
  document.getElementById("ans-sec").classList.add("hidden");
  document.getElementById("ans").textContent="";
}}
function log2(tag,cls,text){{
  const d=document.createElement("div");d.className="line";
  d.innerHTML=`<span class="tag ${{cls}}">${{tag}}</span>${{esc(text)}}`;
  const c=document.getElementById("log");c.appendChild(d);c.scrollTop=c.scrollHeight;
}}
function esc(s){{return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}}
function markDone(name){{
  const el=document.getElementById("n-"+name);if(el)el.className="node done";
  const idx=NODES.indexOf(name);
  if(idx>0){{const a=document.getElementById("a"+(idx-1));if(a)a.className="arr active";}}
}}
async function run(){{
  const q=document.getElementById("q").value.trim();if(!q)return;
  reset();
  const btn=document.getElementById("btn");btn.disabled=true;btn.textContent="Running…";
  log2("start","dt",`question: "${{q}}"`);
  try{{
    const resp=await fetch(`/ui/stream?question=${{encodeURIComponent(q)}}`);
    const reader=resp.body.getReader();const dec=new TextDecoder();let buf="";
    while(true){{
      const{{value,done}}=await reader.read();if(done)break;
      buf+=dec.decode(value,{{stream:true}});
      const parts=buf.split("\\n\\n");buf=parts.pop();
      for(const part of parts){{
        if(!part.trim())continue;
        const lines=part.split("\\n");let et="",ed="";
        for(const l of lines){{if(l.startsWith("event: "))et=l.slice(7).trim();if(l.startsWith("data: "))ed=l.slice(6).trim();}}
        handle(et,ed);
      }}
    }}
  }}catch(e){{log2("error","er",e.message);}}
  btn.disabled=false;btn.textContent="Run";
  NODES.forEach(n=>{{document.getElementById("n-"+n).className="node done";}});
  for(let i=0;i<NODES.length-1;i++)document.getElementById("a"+i).className="arr active";
}}
function handle(et,ed){{
  if(!ed)return;let data;try{{data=JSON.parse(ed);}}catch{{return;}}
  if(et==="updates"){{
    const keys=Object.keys(data);if(!keys.length)return;
    const name=keys[0];log2("node","nd",name);markDone(name);
    const val=data[name];
    if(val?.answer)log2("a2a","a2","answer received ("+String(val.answer).length+" chars)");
    if(val?.tool_results?.length)log2("tool","dt","tools used: "+val.tool_results.map(t=>t.tool).join(", "));
  }}else if(et==="values"){{
    if(data.answer){{document.getElementById("ans-sec").classList.remove("hidden");document.getElementById("ans").textContent=data.answer;}}
  }}else if(et==="error"){{log2("error","er",JSON.stringify(data));}}
}}
</script>
</body>
</html>"""


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=agent_cfg.port, reload=True)
