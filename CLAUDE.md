# A2A Demo — Claude Code Guide

## What this project is

A config-driven demo of the [Google Agent-to-Agent (A2A) protocol](https://github.com/google/A2A).
Two Python/FastAPI agents (Planner + Worker) communicate via A2A JSON-RPC 2.0 with
bearer-token auth and SSE streaming. Every aspect — model, flow, tools, auth — is
controlled by `config.yaml`.

---

## Directory layout

```
A2A/
├── config.yaml          ← MASTER CONFIG: model, flow, tools, auth, endpoints
├── prompts.yaml         ← PROMPT LIBRARY: versioned templates with {{variables}}
├── context.yaml         ← CONTEXT CONFIG: input/output validation, history, injection
├── shared/
│   ├── config.py        ← YAML loader + Pydantic models
│   ├── auth.py          ← BearerAuthMiddleware
│   ├── model_factory.py ← AsyncOpenAI client factory (Groq/Gemini/OpenRouter/Ollama)
│   ├── prompts.py       ← prompt loader + {{var}} renderer + standard_vars()
│   ├── context.py       ← ContextManager: validate_input, build_messages, validate_output
│   ├── outcomes.py      ← OutcomeRecorder: JSONL audit trail + summary stats
│   ├── graph_builder.py ← config-driven LangGraph builder (testable via llm_client param)
│   └── tools/
│       ├── registry.py  ← @register decorator + get_enabled()
│       ├── calculator.py
│       └── web_search.py
├── planner/main.py      ← Planner agent (port 8000)
├── worker/main.py       ← Worker agent (port 8001)
├── tests/
│   ├── conftest.py      ← make_mock_llm(), make_mock_llm_with_tool(), tmp_outcomes fixture
│   ├── unit/            ← 86 tests: config, auth, prompts, context, outcomes, graph, tools
│   └── integration/     ← 19 tests: worker API, planner API (no real LLM/server needed)
├── outcomes/            ← auto-created: YYYY-MM-DD.jsonl audit logs per day
├── pytest.ini
├── requirements-dev.txt
└── docker-compose.yml
```

---

## Running locally (no Docker)

```bash
# 1. Create venv and install
python -m venv .venv && source .venv/bin/activate
pip install -r planner/requirements.txt   # same as worker's

# 2. Set env
cp .env.example .env
# Fill in GROQ_API_KEY (or other provider key)

# 3. Terminal 1 — Worker
cd worker
uvicorn main:app --port 8001 --reload

# 4. Terminal 2 — Planner
cd planner
uvicorn main:app --port 8000 --reload

# 5. Test
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer planner-dev-token" \
  -d '{"question": "What is Docker?"}'

# Trace UI (no auth required):
open http://localhost:8000/ui
```

---

## Running with Docker Compose

```bash
cp .env.example .env     # add GROQ_API_KEY
docker compose up --build
# Trace UI: http://localhost:8000/ui
# Worker health: http://localhost:8001/health
```

---

## Switching AI model — edit config.yaml only

```yaml
# Switch to Groq (free, recommended):
model:
  provider: groq
  model_id: llama-3.1-8b-instant

# Switch to Gemini (free tier):
model:
  provider: gemini
  model_id: gemini-1.5-flash

# Switch to local Ollama:
model:
  provider: ollama
  model_id: llama3.1
```

No Python changes needed. Restart the agent.

---

## Changing the flow — edit config.yaml only

Add or remove nodes and edges in the `flow` section. No Python changes needed.

```yaml
flow:
  entry: receive_question
  nodes:
    - id: receive_question
      type: passthrough
    - id: delegate_to_worker
      type: a2a_delegate
      config:
        target_agent: worker
        streaming: true
    - id: return_answer
      type: passthrough
  edges:
    - [receive_question, delegate_to_worker]
    - [delegate_to_worker, return_answer]
    # Leaf nodes (no outgoing edge) auto-connect to END
```

### Node types

| type | description |
|---|---|
| `passthrough` | Logs state and passes through unchanged |
| `llm_call` | Calls the configured LLM; optional `system_prompt`, `use_tools` |
| `a2a_delegate` | Sends an A2A task to `target_agent`; supports `streaming: true/false` |

---

## Enabling tools — config.yaml + import

**Step 1** — flip `enabled: true` in config.yaml:
```yaml
tools:
  - name: calculator
    enabled: true
```

**Step 2** — make sure the tool is imported in `worker/main.py` (already done for calculator and web_search).

**Adding a new tool:**
1. Create `shared/tools/my_tool.py` with `@register(name="my_tool", ...)`
2. `import shared.tools.my_tool` in `worker/main.py`
3. Add entry under `tools:` in config.yaml
4. Set `enabled: true`

---

## A2A protocol — what this implements

| Feature | Status |
|---|---|
| Agent Card `/.well-known/agent.json` | ✅ |
| JSON-RPC 2.0 envelope | ✅ |
| `tasks/send` (synchronous) | ✅ |
| `tasks/sendSubscribe` (SSE streaming) | ✅ |
| Bearer token authentication | ✅ |
| Message schema `{role, parts: [{type, text}]}` | ✅ |
| Task lifecycle states (working → completed/failed) | ✅ |
| Tool calling (OpenAI function-calling format) | ✅ |
| Push notifications | ❌ not implemented |

---

## Key code pointers

| What | Where |
|---|---|
| Config loading + env interpolation | `shared/config.py:load()` |
| Graph built from YAML | `shared/graph_builder.py:build_graph()` |
| LLM + tool-calling node | `shared/graph_builder.py:_make_llm_call()` |
| A2A delegate node (SSE client) | `shared/graph_builder.py:_make_a2a_delegate()` |
| SSE stream consumer | `shared/graph_builder.py:_consume_sse()` |
| Auth middleware | `shared/auth.py:BearerAuthMiddleware` |
| Tool registry | `shared/tools/registry.py` |
| Worker SSE emitter | `worker/main.py:_stream_task()` |

---

## Free provider reference

| Provider | Sign-up | Free models |
|---|---|---|
| Groq (recommended) | console.groq.com | `llama-3.1-8b-instant`, `llama-3.1-70b-versatile`, `mixtral-8x7b-32768` |
| Gemini | aistudio.google.com | `gemini-1.5-flash`, `gemini-1.5-flash-8b` |
| OpenRouter | openrouter.ai | `meta-llama/llama-3.1-8b-instruct:free`, `mistralai/mistral-7b-instruct:free` |
| Ollama | local | any model: `ollama pull llama3.1` |
