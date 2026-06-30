#!/usr/bin/env bash
# Starts all services in the correct order:
#   1. Docker (Redis + Postgres)
#   2. Ollama server
#   3. FastAPI backend
#   4. React frontend dev server
#
# Usage: ./scripts/run.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

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

echo "==> [1/4] Starting Redis + Postgres (Docker)..."
docker compose -f docker/docker-compose.yml up -d

echo "==> Waiting for Postgres + Redis to be healthy..."
until docker compose -f docker/docker-compose.yml ps --format json | grep -q '"Health":"healthy".*"Health":"healthy"\|healthy'; do
    sleep 1
done
sleep 2

echo "==> [2/4] Starting Ollama server..."
if command -v ollama &> /dev/null; then
    ollama serve > /tmp/ollama.log 2>&1 &
    OLLAMA_PID=$!
    sleep 2
else
    echo "    Ollama not found — skipping (install from https://ollama.com)"
fi

echo "==> [3/4] Starting FastAPI backend..."
# NOTE: backend/app/main.py does not exist yet — placeholder scaffold only.
if [ -f backend/app/main.py ]; then
    uv run uvicorn backend.app.main:app --host "${BACKEND_HOST:-0.0.0.0}" --port "${BACKEND_PORT:-8000}" --reload &
    BACKEND_PID=$!
else
    echo "    backend/app/main.py not implemented yet — skipping."
fi

echo "==> [4/4] Starting React frontend..."
# NOTE: frontend is not yet scaffolded (no package.json) — placeholder scaffold only.
if [ -f frontend/package.json ]; then
    (cd frontend && npm run dev) &
    FRONTEND_PID=$!
else
    echo "    frontend/package.json not found — skipping."
fi

echo ""
echo "==> All available services started. Press Ctrl+C to stop."
wait
