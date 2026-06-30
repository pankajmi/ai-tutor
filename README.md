# AI Tutor (Local)

Local, voice-enabled AI math tutor — CBSE Class 3–10, English only.
Runs fully offline on MacBook M2. See `AGENTS.md` for architecture,
tech stack, and build order.

## Quickstart

```bash
./scripts/setup.sh   # one-time: installs deps, pulls Ollama models
./scripts/run.sh      # starts Redis, Postgres, Ollama, backend, frontend
```

## Structure

```
backend/    FastAPI app (WebSocket + REST)
agents/     LangGraph agents (Tutor, Orchestrator, etc.)
frontend/   React app (Whiteboard, Parent Dashboard)
docker/     docker-compose.yml (Redis, Postgres + pgvector)
scripts/    setup.sh, run.sh
```

Status: scaffold only — no implementation yet. Build layers tracked in
`AGENTS.md`.
