#!/usr/bin/env bash
# One-time setup: install Python deps via uv, prepare env file.
# Usage: ./scripts/setup.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Checking for uv..."
if ! command -v uv &> /dev/null; then
    echo "uv not found. Install it first: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

echo "==> Checking for Docker..."
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Install Docker Desktop before continuing."
    exit 1
fi

echo "==> Creating .env from .env.example (if missing)..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "    Created .env — review and edit values as needed."
else
    echo "    .env already exists, skipping."
fi

echo "==> Syncing Python dependencies via uv..."
uv sync

echo "==> Checking for Ollama..."
if ! command -v ollama &> /dev/null; then
    echo "    Ollama not found. Install from https://ollama.com before running the app."
else
    echo "    Ollama found. Pulling required models (this may take a while)..."
    ollama pull qwen2.5:7b
    ollama pull qwen2.5:1.5b
fi

echo "==> Setup complete. Next: ./scripts/run.sh"
