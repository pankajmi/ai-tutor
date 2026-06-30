# backend/app/llm

Ollama LLM client layer. Subject-agnostic by design — wraps locally-hosted
Ollama models for use by any agent. No tutoring logic, subject behavior,
or prompt content lives here; that belongs entirely to the calling agents
(e.g. Tutor Agent, Mistake Pattern Agent).

## `client.py` — `OllamaClientManager`

Two models, loaded lazily on first access:

| Model | Role | Used by |
|---|---|---|
| `qwen2.5:7b` (primary) | Reasoning-heavy tasks | Tutor Agent, Orchestrator, Problem Generator |
| `qwen2.5:1.5b` (classifier) | Lightweight, always-on classification | Mistake Pattern Agent (background) |

Both model names are configurable via `.env` (`OLLAMA_PRIMARY_MODEL`,
`OLLAMA_CLASSIFIER_MODEL`) — defaults match the table above.

### API

```python
from app.llm import get_ollama_client

client = get_ollama_client()           # process-wide singleton
await client.health_check()             # raises OllamaConnectionError if unreachable/missing models

llm = client.get_primary_llm()          # ChatOllama instance
response = await client.invoke_with_retry(llm, "some prompt")

# Structured output (Pydantic v2)
structured_llm = client.get_structured_llm(MySchema)
result: MySchema = await client.invoke_with_retry(structured_llm, "some prompt")
```

### Singleton

`get_ollama_client()` returns one shared `OllamaClientManager` instance per
process, built from environment variables on first call. All agents should
use this accessor rather than constructing `OllamaClientManager` directly,
so model connections aren't duplicated per-agent.

### Retry behavior

`invoke_with_retry()` wraps any LLM call (`llm.ainvoke(...)`-style) with up
to `max_retries` attempts (default 3) and exponential backoff (default
1s, 2s, 4s...) on failure — covers Ollama being slow to respond, transient
connection resets, etc. Raises `OllamaConnectionError` if all attempts fail.

### Health check

`health_check()` pings Ollama's `/api/tags` endpoint and confirms both the
primary and classifier models are pulled locally. Raises
`OllamaConnectionError` with an actionable message (including the exact
`ollama pull ...` command) if a model is missing.

## Testing

```bash
uv run python backend/app/llm/test_client.py               # primary model
uv run python backend/app/llm/test_client.py --classifier   # classifier model
```

Sends a subject-agnostic sample question ("Explain photosynthesis...") —
deliberately not math, to confirm the client carries no subject-specific
assumptions. Any subject's question should work identically since this
layer has no awareness of subjects at all.

## Prerequisites

- Ollama running locally (`ollama serve`)
- Both models pulled: `ollama pull qwen2.5:7b && ollama pull qwen2.5:1.5b`
