import json
import logging
import os
import uuid
from typing import TypedDict, AsyncIterator

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from langgraph.graph import END, StateGraph

logging.basicConfig(level=logging.INFO, format="%(asctime)s  [planner]  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("planner")

WORKER_URL = os.environ.get("WORKER_URL", "http://localhost:8001")


class PlannerState(TypedDict):
    question: str
    answer: str


def receive_question(state: PlannerState) -> dict:
    log.info("─" * 60)
    log.info(f"[node: receive_question]  question='{state['question']}'")
    return {}


async def delegate_to_worker(state: PlannerState) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        card_resp = await client.get(f"{WORKER_URL}/.well-known/agent.json")
        card_resp.raise_for_status()
        agent_card: dict = card_resp.json()

    log.info(f"[node: delegate_to_worker]  Worker='{agent_card['name']}'  url={agent_card['url']}")

    task_id = str(uuid.uuid4())
    jsonrpc_request = {
        "jsonrpc": "2.0",
        "id": f"req-{task_id}",
        "method": "tasks/send",
        "params": {
            "id": task_id,
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": state["question"]}],
            },
        },
    }

    log.info(f"[A2A →]  POST {WORKER_URL}/")
    log.info(f"[A2A →]  request:\n{json.dumps(jsonrpc_request, indent=2)}")

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{WORKER_URL}/", json=jsonrpc_request)
        resp.raise_for_status()
        jsonrpc_response: dict = resp.json()

    log.info(f"[A2A ←]  response:\n{json.dumps(jsonrpc_response, indent=2)}")

    if "error" in jsonrpc_response:
        raise RuntimeError(f"A2A error from Worker: {jsonrpc_response['error']}")

    result = jsonrpc_response["result"]
    if result["status"]["state"] != "completed":
        raise RuntimeError(f"Unexpected task state: '{result['status']['state']}'")

    return {"answer": result["status"]["message"]["parts"][0]["text"]}


def return_answer(state: PlannerState) -> dict:
    log.info(f"[node: return_answer]  answer ready ({len(state['answer'])} chars)")
    log.info("─" * 60)
    return {}


_builder = StateGraph(PlannerState)
_builder.add_node("receive_question", receive_question)
_builder.add_node("delegate_to_worker", delegate_to_worker)
_builder.add_node("return_answer", return_answer)
_builder.set_entry_point("receive_question")
_builder.add_edge("receive_question", "delegate_to_worker")
_builder.add_edge("delegate_to_worker", "return_answer")
_builder.add_edge("return_answer", END)

graph = _builder.compile()

app = FastAPI(title="Planner Agent")

AGENT_CARD = {
    "name": "Planner Agent",
    "description": "Receives questions and delegates them to Worker agents via A2A",
    "url": os.environ.get("PLANNER_PUBLIC_URL", "http://localhost:8000"),
    "version": "1.0.0",
    "capabilities": {"streaming": False, "pushNotifications": False},
    "skills": [
        {
            "id": "plan-and-answer",
            "name": "Plan and Answer",
            "description": "Delegates questions to the right Worker agent",
            "inputModes": ["text"],
            "outputModes": ["text"],
        }
    ],
}


@app.get("/.well-known/agent.json")
async def agent_card():
    return AGENT_CARD


class Question(BaseModel):
    question: str


@app.post("/ask")
async def ask(body: Question):
    log.info("═" * 60)
    log.info(f"[API /ask]  question='{body.question}'")

    final_state: PlannerState = await graph.ainvoke(
        {"question": body.question, "answer": ""},
    )

    return {"question": body.question, "answer": final_state["answer"]}


_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>A2A Trace Viewer</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Courier New', monospace; background: #0d1117; color: #c9d1d9; min-height: 100vh; padding: 32px; }
  h1 { color: #58a6ff; font-size: 1.4rem; margin-bottom: 6px; }
  .subtitle { color: #8b949e; font-size: 0.8rem; margin-bottom: 32px; }
  .input-row { display: flex; gap: 10px; margin-bottom: 36px; }
  input[type=text] { flex: 1; background: #161b22; border: 1px solid #30363d; border-radius: 6px; color: #c9d1d9; padding: 10px 14px; font-family: inherit; font-size: 0.95rem; outline: none; }
  input[type=text]:focus { border-color: #58a6ff; }
  button { background: #238636; border: none; border-radius: 6px; color: #fff; cursor: pointer; font-family: inherit; font-size: 0.95rem; padding: 10px 22px; }
  button:hover { background: #2ea043; }
  button:disabled { background: #3d444d; cursor: default; }

  .flow { display: flex; align-items: center; gap: 0; margin-bottom: 36px; }
  .node { background: #161b22; border: 2px solid #30363d; border-radius: 10px; padding: 14px 20px; min-width: 170px; text-align: center; transition: all 0.3s; }
  .node .label { font-size: 0.7rem; color: #8b949e; letter-spacing: 0.05em; text-transform: uppercase; margin-bottom: 4px; }
  .node .name { font-size: 0.95rem; color: #c9d1d9; }
  .node.active { border-color: #f0883e; box-shadow: 0 0 18px rgba(240,136,62,0.4); }
  .node.active .name { color: #f0883e; }
  .node.done { border-color: #238636; }
  .node.done .name { color: #3fb950; }
  .arrow { color: #30363d; font-size: 1.4rem; padding: 0 6px; flex-shrink: 0; }
  .arrow.active { color: #3fb950; }

  .section { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 18px; margin-bottom: 16px; }
  .section h2 { color: #8b949e; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 10px; }
  .log-line { font-size: 0.82rem; padding: 2px 0; border-bottom: 1px solid #1c2128; }
  .log-line:last-child { border-bottom: none; }
  .tag { display: inline-block; border-radius: 4px; padding: 1px 7px; font-size: 0.72rem; margin-right: 6px; }
  .tag.node  { background: #1c2d3a; color: #58a6ff; }
  .tag.a2a   { background: #2d1c3a; color: #d2a8ff; }
  .tag.data  { background: #1c2b20; color: #3fb950; }
  .answer-box { background: #0d1117; border: 1px solid #238636; border-radius: 6px; padding: 14px; white-space: pre-wrap; font-size: 0.9rem; line-height: 1.6; color: #c9d1d9; }
  .hidden { display: none; }
</style>
</head>
<body>
<h1>A2A Trace Viewer</h1>
<p class="subtitle">Real-time trace of the Planner → Worker A2A graph &nbsp;·&nbsp; No LangSmith required</p>

<div class="input-row">
  <input type="text" id="q" placeholder="Ask anything… e.g. What is Docker?" value="What is Docker?" />
  <button id="run-btn" onclick="runGraph()">Run</button>
</div>

<div class="flow">
  <div class="node" id="n-receive_question">
    <div class="label">planner node 1</div>
    <div class="name">receive_question</div>
  </div>
  <div class="arrow" id="a1">→</div>
  <div class="node" id="n-delegate_to_worker">
    <div class="label">planner node 2</div>
    <div class="name">delegate_to_worker</div>
  </div>
  <div class="arrow" id="a2">→</div>
  <div class="node" id="n-return_answer">
    <div class="label">planner node 3</div>
    <div class="name">return_answer</div>
  </div>
</div>

<div class="section" id="log-section">
  <h2>Execution log</h2>
  <div id="log-lines"><span style="color:#8b949e;font-size:0.82rem">Waiting for run…</span></div>
</div>

<div class="section hidden" id="answer-section">
  <h2>Answer</h2>
  <div class="answer-box" id="answer-box"></div>
</div>

<script>
const NODES = ["receive_question", "delegate_to_worker", "return_answer"];

function resetUI() {
  NODES.forEach(n => { const el = document.getElementById("n-"+n); el.className = "node"; });
  [1,2].forEach(i => document.getElementById("a"+i).className = "arrow");
  document.getElementById("log-lines").innerHTML = "";
  document.getElementById("answer-section").classList.add("hidden");
  document.getElementById("answer-box").textContent = "";
}

function addLog(tag, cls, text) {
  const div = document.createElement("div");
  div.className = "log-line";
  div.innerHTML = `<span class="tag ${cls}">${tag}</span>${escHtml(text)}`;
  const container = document.getElementById("log-lines");
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function markActive(name) {
  NODES.forEach(n => {
    const el = document.getElementById("n-"+n);
    if (n === name) el.className = "node active";
    else if (el.className === "node active") el.className = "node done";
  });
}

async function runGraph() {
  const question = document.getElementById("q").value.trim();
  if (!question) return;
  resetUI();
  const btn = document.getElementById("run-btn");
  btn.disabled = true;
  btn.textContent = "Running…";

  addLog("start", "data", `question: "${question}"`);

  try {
    // Proxy through /ui/stream on this server (avoids CORS)
    const url = `/ui/stream?question=${encodeURIComponent(question)}`;
    const resp = await fetch(url);
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\\n\\n");
      buf = parts.pop();
      for (const part of parts) {
        if (!part.trim()) continue;
        const lines = part.split("\\n");
        let evtType = "", evtData = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) evtType = line.slice(7).trim();
          if (line.startsWith("data: ")) evtData = line.slice(6).trim();
        }
        handleEvent(evtType, evtData);
      }
    }
  } catch(e) {
    addLog("error", "a2a", e.message);
  }

  btn.disabled = false;
  btn.textContent = "Run";
  NODES.forEach(n => { document.getElementById("n-"+n).className = "node done"; });
  [1,2].forEach(i => document.getElementById("a"+i).className = "arrow active");
}

function handleEvent(evtType, evtData) {
  if (!evtData) return;
  let data;
  try { data = JSON.parse(evtData); } catch { return; }

  if (evtType === "updates") {
    const nodeNames = Object.keys(data);
    if (nodeNames.length) {
      const name = nodeNames[0];
      markActive(name);
      const el = document.getElementById("n-"+name);
      if (el) el.className = "node active";
      addLog("node", "node", name);
      const val = data[name];
      if (val && typeof val === "object") {
        for (const [k, v] of Object.entries(val)) {
          if (k === "answer" && v) {
            addLog("a2a", "a2a", `answer received (${String(v).length} chars)`);
          }
        }
      }
    }
  } else if (evtType === "values") {
    if (data.answer) {
      document.getElementById("answer-section").classList.remove("hidden");
      document.getElementById("answer-box").textContent = data.answer;
    }
  } else if (evtType === "error") {
    addLog("error", "a2a", JSON.stringify(data));
  }
}
</script>
</body>
</html>
"""


@app.get("/ui", response_class=HTMLResponse)
async def trace_ui():
    return _UI_HTML


@app.get("/ui/stream")
async def trace_stream(question: str):
    async def event_generator() -> AsyncIterator[bytes]:
        async for mode, chunk in graph.astream(
            {"question": question, "answer": ""},
            stream_mode=["updates", "values"],
        ):
            data = json.dumps(chunk)
            yield f"event: {mode}\ndata: {data}\n\n".encode()

    return StreamingResponse(event_generator(), media_type="text/event-stream")
