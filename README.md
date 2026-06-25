# Google A2A Protocol – Minimal Learning Demo

A beginner-friendly demonstration of the Google Agent-to-Agent (A2A) protocol using Python, FastAPI, LangGraph, and the Gemini API.

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
                        │  calls LLM API
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
| Worker | 8001 | Receives the A2A task; calls LLM; returns the answer |

---

## A2A Protocol Concepts

### 1. Agent Card (`/.well-known/agent.json`)

Every A2A agent must serve a JSON card at this well-known URL. It details the agent's name, description, capabilities, and list of supported skills (including input and output modes).

```json
{
  "name": "Worker Agent",
  "description": "Answers questions using a configurable AI model",
  "url": "http://worker:8001",
  "version": "2.0.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false
  },
  "skills": [
    {
      "id": "answer-question",
      "name": "Answer Question",
      "description": "Answers any natural-language question",
      "inputModes": ["text"],
      "outputModes": ["text"]
    }
  ]
}
```

### 2. JSON-RPC 2.0 Task Request (`POST /`)

The Planner delegates tasks to the Worker using JSON-RPC 2.0 payloads over HTTP.

```json
{
  "jsonrpc": "2.0",
  "id": "req-abc",
  "method": "tasks/send",
  "params": {
    "id": "task-uuid-here",
    "message": {
      "role": "user",
      "parts": [
        {
          "type": "text",
          "text": "What is LangGraph?"
        }
      ]
    }
  }
}
```

### 3. A2A Task Response

The Worker returns the completed response using JSON-RPC.

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
        "parts": [
          {
            "type": "text",
            "text": "LangGraph is a library for building stateful, multi-actor applications with LLMs."
          }
        ]
      }
    },
    "artifacts": []
  }
}
```

### 4. Task Lifecycle States

Tasks progress through: `submitted` → `working` → `completed` | `failed` | `canceled` | `input-required`.

This demo jumps from `submitted` to `completed` for simplicity.

---

## Project Structure

```
A2A/
├── config.yaml
├── prompts.yaml
├── context.yaml
├── docker-compose.yml
├── run.sh
├── shared/
│   ├── config.py
│   ├── auth.py
│   ├── model_factory.py
│   ├── prompts.py
│   ├── context.py
│   ├── outcomes.py
│   ├── graph_builder.py
│   └── tools/
│       ├── registry.py
│       ├── calculator.py
│       └── web_search.py
├── planner/
│   ├── main.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── langgraph.json
└── worker/
    ├── main.py
    ├── requirements.txt
    ├── Dockerfile
    └── langgraph.json
```

---

## Quick Start

### 1. Prerequisites

- Docker and Docker Compose
- LLM Provider API Keys (Gemini, Groq, or OpenRouter)

### 2. Configure Environment

Copy the example environment file:
```bash
cp .env.example .env
```
Open `.env` and set your API keys (e.g., `GEMINI_API_KEY`, `GROQ_API_KEY`).

### 3. Run Services

Build and start the services:
```bash
docker compose up --build
```

### 4. Test the A2A Flow

```bash
curl -s -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer planner-dev-token" \
  -d '{"question": "What is LangGraph?"}'
```

### 5. Watch the Logs

```bash
docker compose logs -f
```

---

## Configuration Reference

### Master Configuration (`config.yaml`)

The `config.yaml` file defines the models, agents, endpoints, authentication, and providers.

#### Model Registry (`models`)

Defines all available models. Each registry item contains the provider name, model identifier, temperature, max tokens, and a list of API keys.

```yaml
models:
  gemini_flash:
    provider: gemini
    model_id: gemini-1.5-flash
    temperature: 0.1
    max_tokens: 1024
    api_keys:
      - "${GEMINI_API_KEY}"
      - "${GEMINI_API_KEY_2}"

  groq_llama:
    provider: groq
    model_id: llama-3.1-8b-instant
    temperature: 0.1
    max_tokens: 1024
    api_keys:
      - "${GROQ_API_KEY}"
      - "${GROQ_API_KEY_2}"
```

#### API Key Rotation

Under the `api_keys` list, you can provide multiple keys. If the primary key fails or triggers a rate limit, the model chain runner rotates to the next key.

#### Fallback Chain (`model_chain`)

Each agent specifies a `model_chain`. The models in this list are tried sequentially. If a model fails after trying all of its configured API keys, the system falls back to the next model in the chain.

```yaml
agents:
  planner:
    name: "Planner Agent"
    description: "Receives user questions and delegates to Worker agents via A2A"
    port: 8000
    public_url: "${PLANNER_PUBLIC_URL:http://localhost:8000}"
    model_chain:
      - gemini_flash
      - groq_llama
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
    tools: []
    skills:
      - id: plan-and-answer
        name: "Plan and Answer"
        description: "Delegates questions to the right Worker agent"
        input_modes: [text]
        output_modes: [text]
```

#### Node Types in Flow Definition

- `passthrough`: Logs the current state and passes it through unchanged.
- `llm_call`: Makes a call to the active LLM in the configured model chain. Can specify a custom `prompt_id` from `prompts.yaml` and tools configuration.
- `a2a_delegate`: Sends an A2A delegation request to the targeted worker agent.

#### Agent Endpoints

Defines the physical routing URLs for target agents.

```yaml
agent_endpoints:
  worker:
    url: "${WORKER_URL:http://localhost:8001}"
```

#### Authentication

Bearer token security configuration.

```yaml
auth:
  enabled: true
  tokens:
    planner: "${PLANNER_TOKEN:planner-dev-token}"
    worker: "${WORKER_TOKEN:worker-dev-token}"
```

#### Providers

Defines base API URLs for each provider.

```yaml
providers:
  groq:
    base_url: "https://api.groq.com/openai/v1"
  gemini:
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai/"
  openrouter:
    base_url: "https://openrouter.ai/api/v1"
  ollama:
    base_url: "${OLLAMA_URL:http://localhost:11434}/v1"
```

---

### Prompt Library (`prompts.yaml`)

Central library of versioned templates supporting `{{variable}}` substitution.

```yaml
version: "1.0"
prompts:
  worker_default:
    version: "1.0"
    description: "General-purpose worker template"
    template: |
      You are a helpful AI assistant named {{agent_name}}.
      Today's date is {{current_date}}.
      Answer questions clearly, accurately, and concisely.
    variables:
      - agent_name
      - current_date
```

---

### Docker Compose (`docker-compose.yml`)

The docker services are orchestrated as shown below:

```yaml
services:
  worker:
    build:
      context: .
      dockerfile: worker/Dockerfile
    ports:
      - "8001:8001"
    env_file: .env
    environment:
      WORKER_PUBLIC_URL: "http://worker:8001"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"]
      interval: 10s
      timeout: 5s
      retries: 3

  planner:
    build:
      context: .
      dockerfile: planner/Dockerfile
    ports:
      - "8000:8000"
    env_file: .env
    environment:
      WORKER_URL: "http://worker:8001"
      PLANNER_PUBLIC_URL: "http://planner:8000"
    depends_on:
      worker:
        condition: service_healthy
```

---

## LangGraph Studio

Run graph structures locally inside LangGraph Studio:

```bash
cd worker
pip install -r requirements.txt langgraph-cli
langgraph dev
```

---

## Code References

| Module | Purpose |
|--------|---------|
| `shared/config.py` | Config parsing and environment interpolation |
| `shared/model_factory.py` | Handles key rotation and fallback logic across models |
| `shared/graph_builder.py` | Generates graph nodes and edges from configuration |
| `shared/auth.py` | FastAPI middleware validating authentication tokens |
| `shared/context.py` | Validates input/output boundaries and history |
| `shared/outcomes.py` | Records execution audit logs to `outcomes/` |
