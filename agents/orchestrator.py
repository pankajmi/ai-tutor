"""
Orchestrator Agent — LangGraph StateGraph that routes between agents and
manages session state for the multi-subject tutoring app.

Flow:
  1. intent_classifier  → determines if the child wants teaching or practice
  2. tutor_node / problem_gen_node  → calls the appropriate agent
  3. response_assembler → combines spoken_text + whiteboard_commands
  4. mistake_logger_node → fires async background analysis (non-blocking)

Subject is a first-class parameter throughout — no subject-specific logic
is hardcoded in the routing or infrastructure.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal, Optional

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from .models import ChildContext, DrawCommand, Message, TutorResponse
from .stub_mistake_pattern import analyse_turn
from .stub_problem_gen import generate_problem
from .tutor_agent import TutorAgent

logger = logging.getLogger("agents.orchestrator")

# --------------------------------------------------------------------------- #
# Session state
# --------------------------------------------------------------------------- #


class SessionState(TypedDict):
    """Persistent session state, carried across turns."""

    child_id: str
    subject: str
    current_topic: str
    conversation_history: list[Message]
    current_mode: Literal["teaching", "practice", "homework"]
    last_tutor_response: Optional[TutorResponse]
    pending_whiteboard_commands: list[DrawCommand]


class OrchestratorState(TypedDict):
    """Complete graph state: session + per-turn input + internal fields."""

    # Per-turn input
    child_message: str

    # Session state (persistent across turns)
    child_id: str
    subject: str
    current_topic: str
    conversation_history: list[Message]
    current_mode: Literal["teaching", "practice", "homework"]
    last_tutor_response: Optional[TutorResponse]
    pending_whiteboard_commands: list[DrawCommand]

    # Internal (set during graph execution)
    intent: Optional[str]  # "teach" | "practice" | "homework"
    current_tutor_response: Optional[TutorResponse]


# --------------------------------------------------------------------------- #
# Intent classifier
# --------------------------------------------------------------------------- #

_TEACH_KEYWORDS = [
    "explain", "help", "understand", "what is", "how does",
    "i don", "why", "teach", "tell me about", "confused",
    "mean", "show me", "walk me through",
]

_PRACTICE_KEYWORDS = [
    "practice", "problem", "exercise", "give me", "question",
    "try", "test me", "quiz", "worksheet", "more", "another",
]

_HOMEWORK_KEYWORDS = [
    "homework", "assignment", "due", "my teacher", "for class",
]


def _classify_intent(message: str, current_mode: str) -> str:
    """
    Determine the child's intent from their message text.

    If the child is responding to a practice problem (current_mode is
    "practice"), their answer is treated as a teaching turn so the
    tutor can discuss it — the problem_gen node only activates when
    explicitly requested.
    """
    msg_lower = message.lower().strip()

    if current_mode == "practice" and not any(
        kw in msg_lower for kw in _PRACTICE_KEYWORDS + ["next", "another", "more"]
    ):
        return "teach"

    for kw in _HOMEWORK_KEYWORDS:
        if kw in msg_lower:
            return "homework"

    for kw in _PRACTICE_KEYWORDS:
        if kw in msg_lower:
            return "practice"

    return "teach"


async def intent_classifier(state: OrchestratorState) -> dict:
    """Determine the child's intent and set the routing key."""
    intent = _classify_intent(state["child_message"], state["current_mode"])
    logger.info(
        "Intent: %s (mode=%s, msg=%.50s)",
        intent,
        state["current_mode"],
        state["child_message"],
    )
    return {"intent": intent}


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #


def router(state: OrchestratorState) -> str:
    """Return the next node name based on classified intent."""
    intent = state.get("intent", "teach")
    if intent == "practice":
        return "problem_gen_node"
    return "tutor_node"  # teach and homework both route to tutor


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #

_tutor_agent: Optional[TutorAgent] = None


def _get_tutor_agent() -> TutorAgent:
    global _tutor_agent
    if _tutor_agent is None:
        _tutor_agent = TutorAgent()
    return _tutor_agent


async def tutor_node(state: OrchestratorState) -> dict:
    """Call the TutorAgent (persona: Nova) to generate a teaching response."""
    agent = _get_tutor_agent()

    child_ctx = ChildContext(
        grade=5,  # placeholder — real value comes from DB in later layers
        subject=state["subject"],
        weak_topics=[],  # placeholder — will come from MemoryRepository
        current_topic=state["current_topic"],
    )

    response = await agent.ainvoke(
        child_message=state["child_message"],
        child_context=child_ctx,
        conversation_history=state["conversation_history"],
    )

    return {"current_tutor_response": response}


async def problem_gen_node(state: OrchestratorState) -> dict:
    """Call the ProblemGeneratorAgent (stub) to generate a practice problem."""
    response = generate_problem(state["subject"])

    return {
        "current_tutor_response": response,
        "current_mode": "practice",
    }


async def response_assembler(state: OrchestratorState) -> dict:
    """
    Finalise the tutor response: collect whiteboard commands and update
    session history.
    """
    tutor_resp = state.get("current_tutor_response")
    if tutor_resp is None:
        tutor_resp = TutorResponse(
            spoken_text="I'm not sure how to respond to that. Could you rephrase?",
            emotion_signal="neutral",
            topic_detected=None,
        )

    commands = tutor_resp.whiteboard_commands or []

    # Apply any pending whiteboard commands from a previous turn if none
    # were generated this turn (prevents flickering).
    if not commands and state["pending_whiteboard_commands"]:
        commands = state["pending_whiteboard_commands"]

    updated_history = list(state["conversation_history"])
    updated_history.append(Message(role="user", content=state["child_message"]))
    updated_history.append(Message(role="assistant", content=tutor_resp.spoken_text))

    new_topic = tutor_resp.topic_detected or state["current_topic"]

    return {
        "last_tutor_response": tutor_resp,
        "pending_whiteboard_commands": commands,
        "conversation_history": updated_history,
        "current_topic": new_topic,
    }


async def mistake_logger_node(state: OrchestratorState) -> dict:
    """
    Fire-and-forget mistake analysis. Runs in a background task so the
    response is delivered without waiting for classification.
    """
    asyncio.create_task(
        analyse_turn(
            child_message=state["child_message"],
            tutor_response=state.get("current_tutor_response"),
            conversation_history=state["conversation_history"],
            subject=state["subject"],
        )
    )
    return {}


# --------------------------------------------------------------------------- #
# Graph builder
# --------------------------------------------------------------------------- #

_graph_instance = None


def _build_graph():
    builder = StateGraph(OrchestratorState)

    builder.add_node("intent_classifier", intent_classifier)
    builder.add_node("tutor_node", tutor_node)
    builder.add_node("problem_gen_node", problem_gen_node)
    builder.add_node("response_assembler", response_assembler)
    builder.add_node("mistake_logger_node", mistake_logger_node)

    builder.add_edge(START, "intent_classifier")
    builder.add_conditional_edges(
        "intent_classifier",
        router,
        {
            "tutor_node": "tutor_node",
            "problem_gen_node": "problem_gen_node",
        },
    )
    builder.add_edge("tutor_node", "response_assembler")
    builder.add_edge("problem_gen_node", "response_assembler")
    builder.add_edge("response_assembler", "mistake_logger_node")
    builder.add_edge("mistake_logger_node", END)

    return builder.compile()


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


class Orchestrator:
    """
    Top-level orchestrator for the AI tutor system.

    Routes each child utterance to the appropriate agent, updates session
    state, and returns a tutor response.

    Usage:
        orch = Orchestrator()
        session = {
            "child_id": "abc123",
            "subject": "Math",
            ...
        }
        result = await orch.ainvoke("I don't get fractions", session)
        print(result["last_tutor_response"].spoken_text)
    """

    def __init__(self) -> None:
        self._app = _build_graph()

    async def ainvoke(
        self,
        child_message: str,
        session_state: SessionState,
    ) -> SessionState:
        """
        Process a child utterance and return the updated session state.

        Args:
            child_message:  The child's speech transcribed as text.
            session_state:  The current session state (carries history, mode, etc.).

        Returns:
            Updated SessionState with the new tutor_response, whiteboard
            commands, and appended conversation history.
        """
        # Merge session state with per-turn input.
        input_state: OrchestratorState = {
            "child_message": child_message,
            **session_state,  # type: ignore[misc]
            # Internal fields start empty.
            "intent": None,
            "current_tutor_response": None,
        }

        result = await self._app.ainvoke(input_state)

        # Return only the session-state fields (strip internal fields).
        return SessionState(
            child_id=result["child_id"],
            subject=result["subject"],
            current_topic=result["current_topic"],
            conversation_history=result["conversation_history"],
            current_mode=result["current_mode"],
            last_tutor_response=result["last_tutor_response"],
            pending_whiteboard_commands=result["pending_whiteboard_commands"],
        )
