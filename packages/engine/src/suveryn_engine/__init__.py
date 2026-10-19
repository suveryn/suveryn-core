"""Sūveryn engine: the model backend client (llama-server) and the request, answer, citation and calculation schema."""

from .config import LLMSettings
from .llm import BackendError, BackendHealth, LlamaServerClient, StreamChunk
from .schemas import (
    Calculation,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    Citation,
    CitationIssue,
    ModelInfo,
    SourceRef,
    StreamDelta,
    StreamError,
    StreamSources,
    StreamStatus,
    Usage,
)
from .usage import Kind, UsageRecord, UsageRecorder

__all__ = [
    "BackendError",
    "BackendHealth",
    "Calculation",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "Citation",
    "CitationIssue",
    "Kind",
    "LLMSettings",
    "LlamaServerClient",
    "ModelInfo",
    "SourceRef",
    "StreamChunk",
    "StreamDelta",
    "StreamError",
    "StreamSources",
    "StreamStatus",
    "Usage",
    "UsageRecord",
    "UsageRecorder",
]
