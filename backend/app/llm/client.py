"""
Ollama LLM client for the local, multi-subject AI tutor.

Design notes:

- Two models are loaded at init, generic and subject-agnostic by design:
    - PRIMARY (qwen2.5:7b): used by the Tutor Agent, Orchestrator, and
      Problem Generator — anywhere genuine reasoning/dialogue quality
      matters. Subject behavior (math vs science vs language) lives
      entirely in the *prompts* those callers construct, never in this
      client.
    - CLASSIFIER (qwen2.5:1.5b): used by the background Mistake Pattern
      Agent for lightweight, always-on error classification. Kept small
      deliberately — it runs continuously in the background, so cost/
      latency matter more than reasoning depth. This client has no
      knowledge of what it classifies (error types, subjects, etc.);
      that logic belongs entirely to the calling agent.

- This module is intentionally "dumb": it knows how to talk to Ollama,
  retry on transient failures, validate connectivity, and hand back
  LangChain model objects (optionally bound to a Pydantic v2 schema for
  structured output). It has zero opinions about tutoring, subjects, or
  prompts.

- Singleton: one instance shared across all agents, so model connections
  aren't re-established per-agent-instantiation. Use get_ollama_client()
  to access the shared instance.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Type, TypeVar

from langchain_ollama import ChatOllama
from pydantic import BaseModel

logger = logging.getLogger("ai_tutor.llm.client")

T = TypeVar("T", bound=BaseModel)


class OllamaConnectionError(Exception):
    """Raised when Ollama cannot be reached or a required model is unavailable."""


class OllamaClientManager:
    """
    Manages connections to locally-hosted Ollama models.

    Not meant to be instantiated directly by callers — use
    get_ollama_client() to access the process-wide singleton. Direct
    instantiation is still supported for testing with custom config.
    """

    def __init__(
        self,
        base_url: str,
        primary_model: str = "qwen2.5:7b",
        classifier_model: str = "qwen2.5:1.5b",
        max_retries: int = 3,
        initial_backoff_seconds: float = 1.0,
    ) -> None:
        self.base_url = base_url
        self.primary_model_name = primary_model
        self.classifier_model_name = classifier_model
        self.max_retries = max_retries
        self.initial_backoff_seconds = initial_backoff_seconds

        self._primary_llm: Optional[ChatOllama] = None
        self._classifier_llm: Optional[ChatOllama] = None

    # ---------------------------------------------------------------- #
    # Model accessors
    # ---------------------------------------------------------------- #

    def get_primary_llm(self) -> ChatOllama:
        """
        Returns the primary model (qwen2.5:7b) for reasoning-heavy tasks:
        tutor dialogue, orchestration, problem generation. Subject-agnostic
        — callers control behavior entirely via their own prompts.
        """
        if self._primary_llm is None:
            self._primary_llm = ChatOllama(
                base_url=self.base_url,
                model=self.primary_model_name,
            )
        return self._primary_llm

    def get_classifier_llm(self) -> ChatOllama:
        """
        Returns the lightweight classifier model (qwen2.5:1.5b), intended
        for the background Mistake Pattern Agent's always-on error
        classification. Generic LLM handle only — no classification logic
        lives here.
        """
        if self._classifier_llm is None:
            self._classifier_llm = ChatOllama(
                base_url=self.base_url,
                model=self.classifier_model_name,
            )
        return self._classifier_llm

    def get_structured_llm(self, schema: Type[T], use_classifier: bool = False):
        """
        Convenience helper: returns a model bound to a Pydantic v2 schema
        via .with_structured_output(), so callers get validated objects
        back instead of raw text/JSON.

        Args:
            schema: Pydantic v2 model class describing the expected output.
            use_classifier: if True, binds the lightweight classifier model
                instead of the primary model (e.g. for simple structured
                classification outputs).
        """
        base_llm = self.get_classifier_llm() if use_classifier else self.get_primary_llm()
        return base_llm.with_structured_output(schema)

    # ---------------------------------------------------------------- #
    # Health check
    # ---------------------------------------------------------------- #

    async def health_check(self) -> bool:
        """
        Pings Ollama and verifies both the primary and classifier models
        are available (pulled locally). Raises OllamaConnectionError with
        a descriptive message on failure; returns True on success.
        """
        import httpx

        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=5.0) as client:
                response = await client.get("/api/tags")
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise OllamaConnectionError(
                f"Could not reach Ollama at {self.base_url}: {exc}"
            ) from exc

        available_models = {model["name"] for model in data.get("models", [])}

        missing = []
        for required in (self.primary_model_name, self.classifier_model_name):
            # Ollama tags can include a ":latest" suffix or omit it depending
            # on version; check both the exact name and the bare name prefix
            # to avoid false negatives.
            if required not in available_models and not any(
                m.startswith(f"{required}:") or m == required for m in available_models
            ):
                missing.append(required)

        if missing:
            raise OllamaConnectionError(
                f"Ollama is reachable but missing required model(s): {missing}. "
                f"Pull them with: {' && '.join(f'ollama pull {m}' for m in missing)}"
            )

        logger.info(
            "Ollama health check passed. primary=%s classifier=%s",
            self.primary_model_name,
            self.classifier_model_name,
        )
        return True

    # ---------------------------------------------------------------- #
    # Retry wrapper
    # ---------------------------------------------------------------- #

    async def invoke_with_retry(self, llm, *args, **kwargs):
        """
        Invokes an LLM call (llm.ainvoke or a structured-output-bound
        equivalent) with retry + exponential backoff on transient failures
        (e.g. Ollama slow to respond, connection reset).

        Usage:
            llm = client.get_primary_llm()
            response = await client.invoke_with_retry(llm, messages)
        """
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                return await llm.ainvoke(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - intentionally broad; Ollama/
                # network errors surface as varied exception types depending
                # on the underlying HTTP client, and we want to retry all of
                # them uniformly rather than enumerate every possible type.
                last_exc = exc
                if attempt == self.max_retries:
                    break
                backoff = self.initial_backoff_seconds * (2 ** (attempt - 1))
                logger.warning(
                    "Ollama call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt,
                    self.max_retries,
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)

        raise OllamaConnectionError(
            f"Ollama call failed after {self.max_retries} attempts: {last_exc}"
        ) from last_exc


# ---------------------------------------------------------------------- #
# Singleton accessor
# ---------------------------------------------------------------------- #

_singleton_instance: Optional[OllamaClientManager] = None


def get_ollama_client() -> OllamaClientManager:
    """
    Returns the process-wide OllamaClientManager singleton, constructing it
    on first call from environment variables:
        OLLAMA_BASE_URL        (default: http://localhost:11434)
        OLLAMA_PRIMARY_MODEL    (default: qwen2.5:7b)
        OLLAMA_CLASSIFIER_MODEL (default: qwen2.5:1.5b)

    All agents should obtain their LLM handles via this function rather
    than instantiating OllamaClientManager directly, so model connections
    are shared rather than re-established per agent.
    """
    global _singleton_instance

    if _singleton_instance is None:
        import os

        _singleton_instance = OllamaClientManager(
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            primary_model=os.environ.get("OLLAMA_PRIMARY_MODEL", "qwen2.5:7b"),
            classifier_model=os.environ.get("OLLAMA_CLASSIFIER_MODEL", "qwen2.5:1.5b"),
        )

    return _singleton_instance
