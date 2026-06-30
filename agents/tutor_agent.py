"""
Tutor Agent — the core tutoring conversation engine.

Persona "Nova": warm, patient, Socratic. Subject-aware behavior is driven
entirely by the system prompt (never by branching logic in the agent code).
Uses LangGraph StateGraph with a single generation node and Ollama
(qwen2.5:7b) via the shared OllamaClientManager singleton.
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.llm.client import OllamaConnectionError, get_ollama_client

from .models import ChildContext, Message, TutorResponse

logger = logging.getLogger("agents.tutor_agent")

# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #


class TutorAgentState(TypedDict):
    """Per-invocation state for the Tutor Agent node."""

    child_message: str
    child_context: ChildContext
    conversation_history: list[Message]
    tutor_response: Optional[TutorResponse]


# --------------------------------------------------------------------------- #
# System prompt
# --------------------------------------------------------------------------- #

_SUBJECT_GUIDANCE: dict[str, str] = {
    "math": (
        "Use step-by-step Socratic questioning. Break problems into small "
        "logical steps. Ask one question at a time."
    ),
    "science": (
        "Use step-by-step Socratic questioning. Ask the student to make "
        "predictions and observations. Connect concepts to everyday experiences."
    ),
    "english": (
        "Use guided discussion. Ask about word meanings, sentence structure, "
        "and the author's intent. Encourage the student to express their "
        "own thoughts and interpretations."
    ),
    "social studies": (
        "Use exploratory questions. Ask the student to make connections to "
        "what they already know. Encourage critical thinking about different "
        "perspectives and historical context."
    ),
}

SYSTEM_PROMPT_TEMPLATE = (
    "You are Nova, a warm, patient, and encouraging tutor. "
    "You NEVER give the final answer directly — you guide the student "
    "with thoughtful questions, one step at a time.\n\n"
    "Student: grade {grade}, subject: {subject}\n"
    "Current topic: {current_topic}\n"
    "Known weak areas: {weak_areas}\n\n"
    "{subject_guidance}\n\n"
    "Rules:\n"
    "- Keep responses to 2-3 short sentences (they will be spoken aloud).\n"
    "- Ask guiding questions instead of providing answers.\n"
    "- If the student says \"I don't know\", break the problem into smaller steps.\n"
    "- Praise effort and thinking, not just correct answers.\n"
    "- Use English only.\n"
    "- Be warm and encouraging. Never condescending.\n"
    "- Detect the specific topic the student is asking about and set "
    "topic_detected accordingly."
)


def _build_system_prompt(ctx: ChildContext) -> str:
    subject_key = ctx.subject.lower().strip()
    guidance = _SUBJECT_GUIDANCE.get(
        subject_key,
        "Use Socratic questioning. Adapt your approach to the subject matter.",
    )
    return SYSTEM_PROMPT_TEMPLATE.format(
        grade=ctx.grade,
        subject=ctx.subject,
        current_topic=ctx.current_topic or "(not specified)",
        weak_areas=", ".join(ctx.weak_topics) if ctx.weak_topics else "(none yet)",
        subject_guidance=guidance,
    )


# --------------------------------------------------------------------------- #
# LangChain message helpers
# --------------------------------------------------------------------------- #


def _to_langchain_messages(
    system_prompt: str,
    history: list[Message],
    child_message: str,
):
    """Build a list of LangChain messages for the LLM call."""
    messages: list = [SystemMessage(content=system_prompt)]

    for msg in history:
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            messages.append(AIMessage(content=msg.content))

    messages.append(HumanMessage(content=child_message))
    return messages


# --------------------------------------------------------------------------- #
# Graph node
# --------------------------------------------------------------------------- #


async def generate_response(state: TutorAgentState) -> dict:
    """LangGraph node: build prompt → invoke structured LLM → emit response."""
    ctx = state["child_message"]
    _ = ctx  # placate linter; state is consumed below

    child_msg = state["child_message"]
    child_ctx = state["child_context"]
    history = state["conversation_history"]

    system_prompt = _build_system_prompt(child_ctx)
    langchain_messages = _to_langchain_messages(system_prompt, history, child_msg)

    logger.info(
        "Invoking Tutor Agent (subject=%s, topic=%s, turn=%d)",
        child_ctx.subject,
        child_ctx.current_topic,
        len(history) // 2 + 1,
    )

    client = get_ollama_client()
    structured_llm = client.get_structured_llm(TutorResponse)
    try:
        response: TutorResponse = await client.invoke_with_retry(
            structured_llm, langchain_messages
        )
    except OllamaConnectionError:
        logger.exception("Ollama unavailable — Tutor Agent cannot respond.")
        response = TutorResponse(
            spoken_text="I'm sorry, I'm having trouble thinking right now. "
            "Let me try again in a moment.",
            emotion_signal="neutral",
            topic_detected=None,
        )

    return {"tutor_response": response}


# --------------------------------------------------------------------------- #
# Compiled graph
# --------------------------------------------------------------------------- #

_graph: Optional[object] = None


def _build_graph():
    builder = StateGraph(TutorAgentState)
    builder.add_node("generate", generate_response)
    builder.add_edge(START, "generate")
    builder.add_edge("generate", END)
    return builder.compile()


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


class TutorAgent:
    """
    LangGraph-powered Tutor Agent (persona: Nova).

    Usage:
        agent = TutorAgent()
        response = await agent.ainvoke(
            child_message="I don't understand fractions.",
            child_context=ChildContext(grade=5, subject="Math", ...),
            conversation_history=[...],
        )
        print(response.spoken_text)
    """

    def __init__(self) -> None:
        self._app = _build_graph()

    async def ainvoke(
        self,
        child_message: str,
        child_context: ChildContext,
        conversation_history: Optional[list[Message]] = None,
    ) -> TutorResponse:
        """
        Process the child's utterance and return a structured tutor response.

        Args:
            child_message:  The child's speech transcribed as text.
            child_context:  Pedagogical context for the current session.
            conversation_history:  Prior turns (if any).

        Returns:
            TutorResponse with spoken_text, optional whiteboard commands,
            emotion_signal, and detected topic.
        """
        state = TutorAgentState(
            child_message=child_message,
            child_context=child_context,
            conversation_history=conversation_history or [],
            tutor_response=None,
        )
        result = await self._app.ainvoke(state)
        return result["tutor_response"]
