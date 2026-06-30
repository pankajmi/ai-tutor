# AGENTS.md — AI Tutor (Local)

Reference file for AI coding agents (Claude Code etc.) working in this repo.
Keep this file updated as the source of truth for architecture and conventions.

## Project Summary

Local, voice-enabled AI tutor for CBSE, all subjects, Class 3–10, English only.
Runs fully offline on MacBook M2 (no cloud LLM/STT/TTS dependencies).
Multi-agent system built with LangGraph. Replicates a human tuition tutor:
explains concepts (Socratic, never gives direct answers), helps with homework,
generates practice problems, tracks per-child mastery/mistakes, and produces
parent-facing session summaries. Subject is a first-class parameter
throughout (DB schema, agents, WebSocket protocol, dashboard) — no
subject-specific logic should be hardcoded into shared infrastructure
(LLM client, memory layer, orchestrator plumbing). Subject-specific
behavior belongs in agent prompts (e.g. Tutor Agent), not in clients
or data access layers.

## Hardware / Environment Constraints

- Target machine: MacBook Pro M2, 16GB unified memory (24GB if available)
- Everything must run locally — no cloud API calls for STT/TTS/LLM
- Single child session at a time (no multi-tenant scaling concerns yet)
- English only in v1 — do not add Hindi/Hinglish handling unless asked

## Tech Stack

| Layer | Choice |
|---|---|
| STT | whisper.cpp, `medium.en` model, Metal-accelerated |
| VAD | Silero VAD |
| TTS | Kokoro TTS (`kokoro-82m`), streaming/chunked playback |
| LLM (primary) | Ollama, `qwen2.5:7b` |
| LLM (classifier) | Ollama, `qwen2.5:1.5b` |
| Orchestration | LangGraph (StateGraph) |
| Event bus | Redis Pub/Sub |
| Memory (long-term) | PostgreSQL + pgvector |
| Memory (session) | Redis |
| Backend | FastAPI + WebSockets (async) |
| Whiteboard | React + Konva.js (react-konva) |
| Parent dashboard | React (web), Tailwind, recharts |
| Package manager | uv (Python) |
| Infra | Docker Compose (Redis + Postgres), localhost only |

Do not substitute cloud equivalents (e.g. OpenAI Whisper API, ElevenLabs,
GPT-4o, Pinecone) without explicit instruction — the whole point is local-only.

## Repo Structure

```
/backend
  /app
    /voice      STT (whisper.cpp), VAD (silero), TTS (kokoro), voice_loop.py
    /llm        OllamaClientManager — subject-agnostic LLM client (singleton)
    main.py     FastAPI app, WebSocket endpoint, REST routes (later layer)
/agents       LangGraph agents (orchestrator, tutor, problem_gen, mistake_pattern)
/frontend     React app — whiteboard component + parent dashboard
/docker       docker-compose.yml (Redis, Postgres+pgvector)
/scripts      setup.sh, run.sh
/tests        pytest + pytest-asyncio, fixtures for mocked Ollama responses
```

## Agent Roster

| Agent | Responsibility |
|---|---|
| Orchestrator | Routes intent, manages `SessionState` (subject-aware), fans out to other agents |
| Tutor Agent | Persona "Nova". Socratic dialogue, subject-aware behavior driven by `child_context.subject`. Outputs `TutorResponse` |
| Whiteboard Agent | Converts tutor intent into `DrawCommand` list — generic enough for math diagrams, science illustrations, language sentence diagrams, etc. |
| Curriculum Agent | CBSE chapter map per subject, prerequisite gap detection |
| Problem Generator Agent | Difficulty-adaptive problem generation, subject-aware |
| Mistake Pattern Agent | Background classifier (qwen2.5:1.5b): conceptual / procedural / careless — subject-agnostic taxonomy ("procedural" generalizes "calculation" beyond math) |
| Memory Agent | Reads/writes per-child Postgres + Redis state, scoped by subject |
| Parent Reporting Agent | Async, post-session, WhatsApp-style summaries across subjects |

## Core Data Contracts

Always validate LLM output with Pydantic v2. Do not accept raw/unstructured
LLM text where a structured model is defined.

```python
class TutorResponse(BaseModel):
    spoken_text: str                          # max 2-3 sentences, voice-constrained
    whiteboard_commands: list[DrawCommand] | None
    emotion_signal: Literal["encouraging", "neutral", "redirecting"]
    topic_detected: str | None

class DrawCommand(BaseModel):
    type: Literal["write", "highlight", "arrow", "circle", "clear", "box"]
    delay_ms: int
    # + type-specific fields (content/x/y, target_text/color, from/to, cx/cy/r, width/height)
```

```python
class SessionState(TypedDict):
    child_id: str
    subject: str
    current_topic: str
    conversation_history: list[Message]
    current_mode: Literal["teaching", "practice", "homework"]
    last_tutor_response: TutorResponse | None
    pending_whiteboard_commands: list[DrawCommand]
```

## Tutor Agent Behavioral Rules (non-negotiable)

- Never give the final answer directly — ask guiding questions first
- If child says "I don't know" — break problem into smaller steps
- Praise effort, not just correctness ("Good thinking!" not just "Correct!")
- Keep `spoken_text` short — 2–3 sentences max (it gets spoken aloud)
- English only — do not introduce Hindi/Hinglish strings
- Persona name is "Nova" — warm, patient, never condescending
- Subject-aware: tone/approach adapts to `child_context.subject` (e.g.
  step-by-step Socratic questioning for math/science problems, guided
  discussion for language/social studies) — but this adaptation happens
  in the Tutor Agent's prompt construction only, never in shared
  infrastructure (LLM client, memory layer, WebSocket plumbing)

## WebSocket Protocol

Endpoint: `ws://localhost:8000/ws/{child_id}`

```
Client → Server
{ "type": "session_start", "child_id": "...", "subject": "...", "topic": "..." }
{ "type": "speech", "text": "..." }
{ "type": "session_end" }

Server → Client
{ "type": "tutor_speech", "text": "..." }
{ "type": "whiteboard", "commands": [...] }
{ "type": "emotion", "signal": "..." }
{ "type": "error", "message": "..." }
```

`tutor_speech` and `whiteboard` are sent independently as soon as ready —
do not block one on the other. They sync client-side via `delay_ms`.

## Database Schema (Postgres)

```
Child(id, name, grade, created_at)
Subject(id, name)
    -- seed with CBSE subjects: Math, Science, English, Social Studies, etc.
Session(id, child_id, subject_id, started_at, ended_at, topics_covered: JSON)
Mistake(id, child_id, session_id, subject_id, topic, error_type, description, timestamp)
    error_type: enum["conceptual", "procedural", "careless"]
    -- "procedural" generalizes "calculation" beyond math (e.g. a grammar
    -- rule misapplied, a step skipped in a science experiment)
TopicMastery(id, child_id, subject_id, topic, score: float, last_tested_at, attempts: int)
```

Use SQLAlchemy async + asyncpg. Migrations via Alembic. pgvector extension
must be enabled on startup for semantic memory.

## Build Order (do not skip ahead)

1. Project scaffold
2. STT (whisper.cpp + Silero VAD)
3. TTS (Kokoro)
4. Voice loop (STT+TTS connected, barge-in support)
5. Ollama LLM client (singleton, structured output, retries) — subject-agnostic
6. Memory layer (Postgres + pgvector + Redis) — subject-scoped schema
7. Tutor Agent — subject-aware via prompt, not via client/infra changes
8. Orchestrator (LangGraph StateGraph)
9. WebSocket backend (FastAPI)
10. Whiteboard (React + Konva.js)
11. Parent dashboard (React) — subject selector/tabs
12. Integration test (pytest, mocked Ollama fixtures) — test at least one
    non-math subject explicitly to catch hidden math-only assumptions

Stub agents (`ProblemGeneratorAgent`, `MistakePatternAgent`) are acceptable
placeholders until their dedicated layer is reached — don't over-build early.

## Conventions

- Python 3.11+, async-first throughout (FastAPI, SQLAlchemy, agents)
- All LLM-facing I/O models defined as Pydantic v2 classes, validated via
  `.with_structured_output()`
- Ollama client is a singleton (`OllamaClientManager`) — do not instantiate
  per-request
- Retry policy for Ollama calls: 3 attempts, exponential backoff
- Tests: pytest + pytest-asyncio, mock Ollama with recorded fixtures
  (no live model calls in CI/test runs)
- No cloud API keys should be required to run this project end-to-end

## Out of Scope (v1)

- Hindi / Hinglish voice or text
- Multi-child concurrent sessions
- Cloud deployment / multi-tenant infra
- Boards other than CBSE
