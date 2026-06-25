#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VENV="$SCRIPT_DIR/.venv"
PYTHON="$VENV/bin/python3"
PIP="$VENV/bin/pip"
UVICORN="$VENV/bin/uvicorn"
LANGGRAPH="$VENV/bin/langgraph"


RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}▸ $*${RESET}"; }
success() { echo -e "${GREEN}✓ $*${RESET}"; }
warn()    { echo -e "${YELLOW}⚠ $*${RESET}"; }
die()     { echo -e "${RED}✗ $*${RESET}" >&2; exit 1; }


check_env() {
    if [ ! -f "$SCRIPT_DIR/.env" ]; then
        touch "$SCRIPT_DIR/.env"
    fi

    set -o allexport
    source "$SCRIPT_DIR/.env"
    set +o allexport
}


run_docker() {
    command -v docker >/dev/null 2>&1 || die "Docker is not installed."
    docker compose version >/dev/null 2>&1 || die "Docker Compose is not installed."

    info "Building and starting Planner (port 8000) and Worker (port 8001)…"
    echo ""

    cd "$SCRIPT_DIR"
    docker compose up --build
}


run_test() {
    command -v curl >/dev/null 2>&1 || die "curl is not installed."

    PLANNER_URL="${PLANNER_URL:-http://localhost:8000}"
    QUESTION="${2:-What is LangGraph?}"

    info "Sending question to Planner at $PLANNER_URL/ask"
    info "Question: \"$QUESTION\""
    echo ""

    RESPONSE=$(curl -sf -X POST "$PLANNER_URL/ask" \
        -H "Content-Type: application/json" \
        -d "{\"question\": \"$QUESTION\"}" \
    ) || die "Request failed. Is the Planner running? Try './run.sh docker' first."

    echo -e "${BOLD}Response:${RESET}"
    echo "$RESPONSE" | "$PYTHON" -m json.tool 2>/dev/null || echo "$RESPONSE"
}


WORKER_PID=""

cleanup_worker() {
    if [ -n "$WORKER_PID" ] && kill -0 "$WORKER_PID" 2>/dev/null; then
        info "Stopping background Worker (pid $WORKER_PID)…"
        kill "$WORKER_PID" 2>/dev/null || true
    fi
}

run_studio() {
    AGENT="${2:-worker}"

    [ -f "$LANGGRAPH" ] || die "Venv not found at $VENV.\nRun: python3 -m venv .venv && .venv/bin/pip install -r worker/requirements.txt -r planner/requirements.txt langgraph-cli[inmem]"

    case "$AGENT" in

        worker)
            info "Opening Worker graph in LangGraph Studio…"
            info "Input to use in Studio:"
            echo '  { "task_id": "demo-001", "question": "What is LangGraph?", "answer": "" }'
            echo ""
            cd "$SCRIPT_DIR/worker"
            exec "$LANGGRAPH" dev
            ;;

        planner)

            info "Starting Worker in background on port 8001…"

            WORKER_URL="http://localhost:8001" \
            WORKER_PUBLIC_URL="http://localhost:8001" \
                "$UVICORN" worker.main:app --host 0.0.0.0 --port 8001 --log-level warning &

            WORKER_PID=$!
            trap cleanup_worker EXIT

            info "Waiting for Worker to be ready…"
            for i in $(seq 1 20); do
                if curl -sf http://localhost:8001/.well-known/agent.json >/dev/null 2>&1; then
                    success "Worker is up."
                    break
                fi
                sleep 1
                if [ "$i" -eq 20 ]; then
                    die "Worker did not start in time."
                fi
            done

            info "Opening Planner graph in LangGraph Studio…"
            info "Input to use in Studio:"
            echo '  { "question": "What is LangGraph?", "answer": "" }'
            echo ""

            cd "$SCRIPT_DIR/planner"
            WORKER_URL="http://localhost:8001" \
                exec "$LANGGRAPH" dev
            ;;

        *)
            die "Unknown agent '$AGENT'. Use: ./run.sh studio worker|planner"
            ;;
    esac
}


MODE="${1:-docker}"

check_env

case "$MODE" in
    docker)         run_docker ;;
    test)           run_test "$@" ;;
    studio)         run_studio "$@" ;;
    *)              die "Unknown mode '$MODE'.\nUsage: ./run.sh [docker|test|studio worker|studio planner]" ;;
esac
