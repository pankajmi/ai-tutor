"""
LLM client layer for the AI tutor. Subject-agnostic by design — wraps
Ollama models for use by any agent, with no tutoring/subject logic here.
"""
from .client import OllamaClientManager, OllamaConnectionError, get_ollama_client

__all__ = ["OllamaClientManager", "OllamaConnectionError", "get_ollama_client"]
