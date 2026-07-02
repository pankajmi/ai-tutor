#!/usr/bin/env bash
# Starts all services for the end-to-end AI tutor experience.
#
# Usage:
#   ./scripts/run.sh                        # server + frontend (no voice)
#   ./scripts/run.sh --voice                # server + frontend + voice mic/speaker
#   ./scripts/run.sh --voice --subject Science --topic "Photosynthesis"
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# ── Parse args ─────────────────────────────────────────────────────────────
VOICE=0
SUBJECT="Math"
TOPIC=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --voice) VOICE=1; shift ;;
    --subject) SUBJECT="$2"; shift 2 ;;
    --topic) TOPIC="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [ ! -f .env ]; then
    echo "No .env found. Run ./scripts/setup.sh first."
    exit 1
fi

set -a
source .env
set +a

cleanup() {
    echo ""
    echo "==> Shutting down..."
    [ -n "${OLLAMA_PID:-}" ] && kill "$OLLAMA_PID" 2>/dev/null || true
    [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null || true
    [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null || true
    docker compose -f docker/docker-compose.yml down
}
trap cleanup EXIT INT TERM

# ── [1/4] Docker: Redis + Postgres ───────────────────────────────────────
echo "==> [1/4] Starting Redis + Postgres (Docker)..."
# Idempotent: if containers already exist (e.g. from a previous run), just
# start them; otherwise create them.
if docker inspect ai-tutor-postgres ai-tutor-redis > /dev/null 2>&1; then
    docker start ai-tutor-postgres ai-tutor-redis 2>/dev/null || true
else
    docker compose -f docker/docker-compose.yml up -d
fi

echo "==> Waiting for Postgres + Redis to be healthy..."
# Use docker inspect to check the container's built-in health status
# (avoids 'exec' issues when containers were started by a different invocation).
wait_for_health() {
  local name="$1"
  local label="$2"
  until [ "$(docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null)" = "healthy" ]; do
    printf "    waiting for %s...\r" "$label"
    sleep 2
  done
  echo "    $label is healthy."
}
wait_for_health ai-tutor-postgres "PostgreSQL"
wait_for_health ai-tutor-redis "Redis"

# ── [2/4] Ollama ──────────────────────────────────────────────────────────
echo "==> [2/4] Starting Ollama server..."
if command -v ollama &> /dev/null; then
    ollama serve > /tmp/ollama.log 2>&1 &
    OLLAMA_PID=$!
    sleep 2
    # Verify models are pulled
    for model in qwen2.5:7b qwen2.5:1.5b; do
        if ! ollama list 2>/dev/null | grep -q "$model"; then
            echo "    Pulling $model (this may take a while)..."
            ollama pull "$model"
        fi
    done
else
    echo "    Ollama not found — skipping (install from https://ollama.com)"
fi

# ── [3/4] Backend (FastAPI server ± voice) ────────────────────────────────
echo "==> [3/4] Starting backend on port ${BACKEND_PORT:-8000}..."

if [ "$VOICE" -eq 1 ]; then
    # run_server.py combines uvicorn + voice session in one process
    uv run python backend/run_server.py \
        --port "${BACKEND_PORT:-8000}" \
        --subject "$SUBJECT" \
        --topic "$TOPIC" \
        --child-id "${CHILD_ID:-local_child}" &
    BACKEND_PID=$!
else
    # Server only (no mic/speaker)
    cd backend
    uv run uvicorn app.main:app \
        --host "${BACKEND_HOST:-0.0.0.0}" \
        --port "${BACKEND_PORT:-8000}" \
        --reload &
    BACKEND_PID=$!
    cd "$ROOT_DIR"
fi
sleep 3

# ── [4/4] Frontend (Vite dev server) ──────────────────────────────────────
echo "==> [4/4] Starting React frontend on :5173..."
if [ -f frontend/package.json ]; then
    if [ ! -d frontend/node_modules ]; then
        echo "    Installing frontend dependencies..."
        (cd frontend && npm install)
    fi
    (cd frontend && npm run dev) &
    FRONTEND_PID=$!
else
    echo "    frontend/package.json not found — skipping."
fi

echo ""
echo "=============================================="
echo "  Frontend: http://localhost:5173/"
echo "  Dashboard: http://localhost:5173/dashboard?child_id=${CHILD_ID:-local_child}"
echo "  Backend API: http://localhost:${BACKEND_PORT:-8000}/docs"
echo "  Whiteboard WS: ws://localhost:${BACKEND_PORT:-8000}/ws/{child_id}"
if [ "$VOICE" -eq 1 ]; then
    echo "  Voice: ON (subject=$SUBJECT, topic=$TOPIC)"
    echo "  Speak into your mic — press Ctrl+C to stop."
fi
echo "=============================================="
echo ""
wait
