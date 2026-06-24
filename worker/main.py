import json
import logging
import os
from typing import TypedDict

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langgraph.graph import END, StateGraph

logging.basicConfig(level=logging.INFO, format="%(asctime)s  [worker]  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("worker")


def ask_ai(question: str) -> str:
    resp = httpx.post(
        "https://text.pollinations.ai/openai",
        json={"model": "openai", "messages": [{"role": "user", "content": question}], "private": True},
        headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"},
        timeout=30,
        follow_redirects=True,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


class WorkerState(TypedDict):
    task_id: str
    question: str
    answer: str


def receive_task(state: WorkerState) -> dict:
    log.info("─" * 60)
    log.info(f"[node: receive_task]  task_id={state['task_id']}  question='{state['question']}'")
    return {}


def call_ai(state: WorkerState) -> dict:
    log.info("[node: call_ai]  calling Pollinations AI…")
    answer = ask_ai(state["question"])
    log.info(f"[node: call_ai]  received {len(answer)} chars")
    return {"answer": answer}


def format_response(state: WorkerState) -> dict:
    log.info(f"[node: format_response]  task {state['task_id']} complete")
    return {}


_builder = StateGraph(WorkerState)
_builder.add_node("receive_task", receive_task)
_builder.add_node("call_ai", call_ai)
_builder.add_node("format_response", format_response)
_builder.set_entry_point("receive_task")
_builder.add_edge("receive_task", "call_ai")
_builder.add_edge("call_ai", "format_response")
_builder.add_edge("format_response", END)

graph = _builder.compile()

app = FastAPI(title="Worker Agent")

AGENT_CARD = {
    "name": "Worker Agent",
    "description": "Answers questions using Pollinations AI",
    "url": os.environ.get("WORKER_PUBLIC_URL", "http://localhost:8001"),
    "version": "1.0.0",
    "capabilities": {"streaming": False, "pushNotifications": False},
    "skills": [
        {
            "id": "answer-question",
            "name": "Answer Question",
            "description": "Answers any natural-language question",
            "inputModes": ["text"],
            "outputModes": ["text"],
        }
    ],
}


@app.get("/.well-known/agent.json")
async def agent_card():
    return AGENT_CARD


@app.post("/")
async def a2a_endpoint(request: Request):
    body: dict = await request.json()
    jsonrpc_id = body.get("id")
    method: str = body.get("method", "")
    params: dict = body.get("params", {})

    log.info("═" * 60)
    log.info(f"[A2A ←]  method='{method}'  id={jsonrpc_id}")
    log.info(f"[A2A ←]  payload:\n{json.dumps(body, indent=2)}")

    if method != "tasks/send":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": jsonrpc_id,
            "error": {"code": -32601, "message": f"Method not supported: '{method}'"},
        })

    task_id: str = params["id"]
    question: str = params["message"]["parts"][0]["text"]

    final_state: WorkerState = graph.invoke(
        {"task_id": task_id, "question": question, "answer": ""},
    )

    response_body = {
        "jsonrpc": "2.0",
        "id": jsonrpc_id,
        "result": {
            "id": task_id,
            "status": {
                "state": "completed",
                "message": {
                    "role": "agent",
                    "parts": [{"type": "text", "text": final_state["answer"]}],
                },
            },
            "artifacts": [],
        },
    }

    log.info(f"[A2A →]  task {task_id} completed")
    log.info(f"[A2A →]  response:\n{json.dumps(response_body, indent=2)}")

    return JSONResponse(response_body)
