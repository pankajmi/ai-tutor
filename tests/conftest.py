"""
pytest fixtures for integration tests.

Provides:
- mock_ollama: replaces the OllamaClientManager singleton with a mock that
  returns pre-recorded TutorResponse objects from fixture JSON files.
- db_session: async SQLAlchemy session for test DB setup/teardown.
- seed_child: creates a test child record in Postgres.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, AsyncGenerator

import pytest_asyncio
from pytest import FixtureRequest

from agents.models import TutorResponse

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# --------------------------------------------------------------------------- #
# Fixture: load recorded TutorResponse list from JSON
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
def recorded_responses(request: FixtureRequest) -> list[TutorResponse]:
    """Load a recorded fixture JSON and parse into TutorResponse objects.

    Usage in a test:
        def test_foo(recorded_responses):
            resp = recorded_responses[0]  # first turn
    """
    marker = request.node.get_closest_marker("fixture_file")
    filename = marker.args[0] if marker else "science_photosynthesis.json"
    path = FIXTURES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Fixture file not found: {path}")
    with open(path) as f:
        raw = json.load(f)
    return [TutorResponse(**r) for r in raw]


# --------------------------------------------------------------------------- #
# Fixture: mock OllamaClientManager
# --------------------------------------------------------------------------- #


class _MockOllamaClient:
    """Replaces OllamaClientManager for deterministic testing.

    Returns pre-recorded TutorResponse objects in sequence.
    """

    def __init__(self, responses: list[TutorResponse]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.call_count = 0
        self.called_with: list[Any] = []

    def get_primary_llm(self):
        return self

    def get_classifier_llm(self):
        return self

    def get_structured_llm(self, schema=None, use_classifier=False):
        return self

    async def ainvoke(self, messages=None):
        """Used when the mock itself acts as the LLM."""
        return await self.invoke_with_retry(None, messages)

    async def invoke_with_retry(self, llm, messages, *args, **kwargs):
        self.call_count += 1
        self.called_with.append(kwargs.get("messages", messages))

        if self._index < len(self._responses):
            resp = self._responses[self._index]
            self._index += 1
            return resp

        raise RuntimeError(
            f"MockOllamaClient exhausted after {len(self._responses)} calls. "
            f"Test called invoke_with_retry {len(self._responses) + 1} times."
        )


@pytest_asyncio.fixture
async def mock_ollama(recorded_responses, monkeypatch):
    """Replace get_ollama_client() with a mock that returns recorded responses.

    Also clears cached singletons so each test creates fresh graph instances
    that pick up the mocked client.
    """
    mock = _MockOllamaClient(recorded_responses)

    import agents.tutor_agent as ta
    import agents.orchestrator as orch

    monkeypatch.setattr(ta, "get_ollama_client", lambda: mock)

    # Clear cached singletons so next agent/graph creation uses the mock
    orch._graph_instance = None
    orch._tutor_agent = None
    ta._graph = None

    yield mock


# --------------------------------------------------------------------------- #
# Fixture: DB session
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator:
    """Provide a fresh async DB session for test setup/teardown."""
    from app.db.database import async_session_factory
    from app.db.models import Base
    from app.db.database import engine

    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as sess:
        yield sess

    await engine.dispose()


# --------------------------------------------------------------------------- #
# Fixture: seed test child + subject
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def seed_child(db_session) -> str:
    """Create a test child and ensure the 'science' subject exists.

    Returns the child_id for use in tests.
    """
    from app.db.models import Child, Subject

    child_id = "test_integration_science"

    # Upsert child
    child = await db_session.get(Child, child_id)
    if child is None:
        db_session.add(Child(id=child_id, name="Test Runner", grade=6))
        await db_session.commit()

    # Upsert subject
    subject = await db_session.get(Subject, "science")
    if subject is None:
        db_session.add(Subject(id="science", name="Science"))
        await db_session.commit()

    return child_id
