# Google A2A Protocol – Minimal Learning Demo

A beginner-friendly demonstration of the **Google Agent-to-Agent (A2A) protocol**
using Python, FastAPI, LangGraph, and the Gemini API.

---

## What this demo shows

```
User → POST /ask → [Planner Agent]
                        │
                        │  ① GET  /.well-known/agent.json   (A2A discovery)
                        │  ② POST /   tasks/send  JSON-RPC  (A2A delegation)
                        ▼
               [Worker Agent]
                        │
                        │  calls Gemini API
                        ▼
                   answer text
                        │
                        │  ③ A2A JSON-RPC response
                        ▼
             [Planner Agent] → response to User
```

### Agents

| Agent | Port | Role |
|-------|------|------|
| Planner | 8000 | Receives the user's question; delegates to Worker via A2A |
| Worker | 8001 | Receives the A2A task; calls Gemini; returns the answer |

---

## A2A Protocol Concepts

### 1  Agent Card  (`/.well-known/agent.json`)
Every A2A agent must serve a JSON "business card" at this well-known URL.
It tells the world the agent's name, what it can do (skills), and where to
send tasks.  Like an OpenAPI spec for inter-agent discovery.

```json
{
  "name": "Worker Agent",
  "description": "Answers questions using the Gemini API",
  "url": "http://worker:8001",
  "capabilities": { "streaming": false, "pushNotifications": false },
  "skills": [{ "id": "answer-question", "name": "Answer Question" }]
}
```

### 2  JSON-RPC 2.0 Task Request  (`POST /`)
The Planner sends a task to the Worker using JSON-RPC 2.0 over HTTP.

```json
{
  "jsonrpc": "2.0",
  "id": "req-abc",
  "method": "tasks/send",
  "params": {
    "id": "task-uuid-here",
    "message": {
      "role": "user",
      "parts": [{ "type": "text", "text": "What is LangGraph?" }]
    }
  }
}
```

### 3  A2A Task Response
The Worker replies with the completed task.

```json
{
  "jsonrpc": "2.0",
  "id": "req-abc",
  "result": {
    "id": "task-uuid-here",
    "status": {
      "state": "completed",
      "message": {
        "role": "agent",
        "parts": [{ "type": "text", "text": "LangGraph is a library for …" }]
      }
    },
    "artifacts": []
  }
}
```

### 4  Task Lifecycle States
`submitted` → `working` → `completed` | `failed` | `canceled` | `input-required`

This demo jumps straight from submitted to completed for simplicity.

---

## Project Structure

```
A2A/
├── .env.example          ← copy to .env and add your Gemini API key
├── docker-compose.yml
├── planner/
│   ├── main.py           ← Planner Agent (FastAPI + LangGraph)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── langgraph.json    ← LangGraph Studio config
└── worker/
    ├── main.py           ← Worker Agent (FastAPI + LangGraph)
    ├── requirements.txt
    ├── Dockerfile
    └── langgraph.json    ← LangGraph Studio config
```

---

## Quick Start

### 1  Prerequisites
- Docker + Docker Compose
- A Gemini API key → https://aistudio.google.com/app/apikey

### 2  Configure
```bash
cp .env.example .env
# Edit .env and set your GEMINI_API_KEY
```

### 3  Run
```bash
docker compose up --build
```

You should see both agents start up and print their URLs.

### 4  Test the full A2A flow
```bash
curl -s -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is LangGraph?"}' | python3 -m json.tool
```

### 5  Watch the logs
In a separate terminal:
```bash
docker compose logs -f
```

You'll see the exact JSON payloads crossing the wire between the two agents.

---

## LangGraph Studio

LangGraph Studio lets you visualise and step through the graph execution.

### Option A – Inspect the graph structure locally (no Worker needed)

```bash
# In one terminal – run the Worker so the Planner can reach it
cd worker && pip install -r requirements.txt
WORKER_PUBLIC_URL=http://localhost:8001 uvicorn main:app --port 8001

# In another terminal – open Planner in Studio
cd planner && pip install -r requirements.txt langgraph-cli
WORKER_URL=http://localhost:8001 langgraph dev
```

```bash
# Or inspect the Worker graph in Studio
cd worker && pip install -r requirements.txt langgraph-cli
langgraph dev
```

Studio opens in your browser and shows the graph nodes and edges.
You can run the graph step-by-step with custom inputs.

### Option B – Point Studio at the Docker Compose stack

Start Docker Compose first, then use `langgraph dev` with the env variables
already set in docker-compose.yml (WORKER_URL=http://localhost:8001 works
because port 8001 is published to the host).

---

## Understanding the Code

| File | Key things to read |
|------|--------------------|
| `worker/main.py` | `AGENT_CARD` dict, `a2a_endpoint()` handler, `WorkerState` |
| `planner/main.py` | `delegate_to_worker()` node – the A2A round-trip |
| `docker-compose.yml` | How `WORKER_URL` switches between Docker names and localhost |

The most important code to read first is the `delegate_to_worker` node in
`planner/main.py` – it is the entire A2A client in ~30 lines.

---

## Extending the Demo

**Add a second Worker**: give it a different skill (e.g. `"code-generation"`),
then make the Planner choose between workers based on the question.

**Add streaming**: set `"streaming": true` in the Agent Card, implement
`tasks/sendSubscribe` using Server-Sent Events, and consume the stream
in the Planner's delegate node.

**Add task status polling**: instead of a synchronous response, have the
Worker return `state: "working"` immediately, then implement `tasks/get`
so the Planner can poll for completion.
