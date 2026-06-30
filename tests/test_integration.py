"""
End-to-end integration test for the AI tutor.

Simulates a full 4-turn tutoring session on Science / Photosynthesis
without voice hardware, using recorded Ollama fixture responses.

Confirms the system is genuinely subject-agnostic by testing a non-math
subject end-to-end through the Orchestrator.  All 4 turns run inside a
single async test method because session state carries across turns.
"""

from __future__ import annotations

import pytest

from agents.models import TutorResponse
from agents.orchestrator import Orchestrator, SessionState

pytestmark = pytest.mark.fixture_file("science_photosynthesis.json")


class TestFullScienceSession:
    """4-turn photosynthesis tutoring session."""

    @pytest.fixture(autouse=True)
    def _setup(self, mock_ollama, seed_child, db_session):
        self.mock = mock_ollama
        self.child_id = seed_child
        self.db = db_session

    async def test_full_session(self):
        orch = Orchestrator()

        session: SessionState = SessionState(
            child_id=self.child_id,
            subject="science",
            current_topic="photosynthesis",
            conversation_history=[],
            current_mode="teaching",
            last_tutor_response=None,
            pending_whiteboard_commands=[],
        )

        # ── Turn 1 ──────────────────────────────────────────────
        session = await orch.ainvoke(
            "I don't understand how plants make their own food",
            session,
        )
        resp: TutorResponse = session["last_tutor_response"]
        assert resp is not None, "Turn 1: expected a TutorResponse"
        assert resp.spoken_text, "Turn 1: spoken_text should be non-empty"
        assert isinstance(resp.whiteboard_commands, list), (
            "Turn 1: whiteboard_commands should be a list"
        )
        assert resp.emotion_signal in ("encouraging", "neutral", "redirecting")
        # Nova must NOT give away the answer on turn 1
        for word in ("glucose", "oxygen", "C6H12O6", "CO2"):
            assert word.lower() not in resp.spoken_text.lower(), (
                f"Turn 1: Nova should not reveal '{word}' this early"
            )
        # Nova should ask a guiding question
        assert "?" in resp.spoken_text, "Turn 1: Nova must ask a question"

        # ── Turn 2 ──────────────────────────────────────────────
        session = await orch.ainvoke(
            "why do they need sunlight specifically",
            session,
        )
        resp = session["last_tutor_response"]
        assert resp is not None, "Turn 2: expected a TutorResponse"
        assert resp.spoken_text, "Turn 2: spoken_text should be non-empty"
        assert "glucose" not in resp.spoken_text.lower(), (
            "Turn 2: should not reveal 'glucose' yet"
        )

        # ── Turn 3 ──────────────────────────────────────────────
        session = await orch.ainvoke(
            "so sunlight, water, and carbon dioxide all combine?",
            session,
        )
        resp = session["last_tutor_response"]
        assert resp is not None, "Turn 3: expected a TutorResponse"
        assert resp.spoken_text, "Turn 3: spoken_text should be non-empty"
        # Nova should affirm the student's correct reasoning
        assert any(
            w in resp.spoken_text.lower()
            for w in ("right", "exactly", "correct", "yes", "good")
        ), "Turn 3: Nova should affirm the student's correct thinking"

        # ── Turn 4 ──────────────────────────────────────────────
        session = await orch.ainvoke(
            "and that makes glucose and oxygen, right?",
            session,
        )
        resp = session["last_tutor_response"]
        assert resp is not None, "Turn 4: expected a TutorResponse"
        assert resp.spoken_text, "Turn 4: spoken_text should be non-empty"
        assert isinstance(resp.whiteboard_commands, list), (
            "Turn 4: whiteboard_commands should be a list"
        )
        # Final turn should be encouraging
        assert resp.emotion_signal == "encouraging", (
            f"Turn 4: expected 'encouraging', got '{resp.emotion_signal}'"
        )
        # Nova should enthusiastically affirm the correct answer
        assert any(
            w in resp.spoken_text.lower()
            for w in ("excellent", "perfect", "correct", "right", "great")
        ), "Turn 4: Nova should enthusiastically affirm"

        # ── Post-session: verify TopicMastery can be persisted ───
        from app.db.repository import MemoryRepository
        from app.db.models import TopicMastery
        from sqlalchemy import select

        # Simulate what the persistence layer will do after a session:
        # create/update a TopicMastery row for the topic discussed.
        repo = MemoryRepository(self.db)
        await repo.update_mastery(
            child_id=self.child_id,
            subject_id="science",
            topic="photosynthesis",
            score_delta=0.15,  # correct answer → small positive delta
        )

        # Verify it was written
        stmt = select(TopicMastery).where(
            TopicMastery.child_id == self.child_id,
            TopicMastery.subject_id == "science",
            TopicMastery.topic == "photosynthesis",
        )
        result = await self.db.execute(stmt)
        mastery = result.scalar_one_or_none()

        assert mastery is not None, (
            "Expected TopicMastery row for science/photosynthesis"
        )
        assert isinstance(mastery.score, float)
        assert 0.0 <= mastery.score <= 1.0, (
            f"score should be in [0, 1], got {mastery.score}"
        )
        assert mastery.attempts >= 1, (
            f"expected >= 1 attempt, got {mastery.attempts}"
        )
        # Verify the score delta was applied
        assert mastery.score == 0.15, (
            f"expected score 0.15, got {mastery.score}"
        )

        # ── Cleanup ────────────────────────────────────────────
        from sqlalchemy import delete

        stmt = delete(TopicMastery).where(TopicMastery.id == mastery.id)
        await self.db.execute(stmt)
        await self.db.commit()
