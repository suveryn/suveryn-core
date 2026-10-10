"""Sūveryn engine: the model backend client (llama-server) and the request, answer, citation and calculation schema."""

from .config import LLMSettings
from .llm import BackendError, BackendHealth, LlamaServerClient, StreamChunk
from .schemas import (
    Calculation,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    Citation,
    ModelInfo,
    SourceRef,
    StreamDelta,
    StreamError,
    Usage,
)

__all__ = [
    "BackendError", "BackendHealth", "Calculation", "ChatMessage", "ChatRequest", "ChatResponse", "Citation",
    "LLMSettings", "LlamaServerClient", "ModelInfo", "SourceRef", "StreamChunk", "StreamDelta", "StreamError", "Usage",
]
