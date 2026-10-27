"""The sūveryn harness: everything between a question and the model, and between the model and the
person (docs/harness.md). What the model is given (the grounded prompt, document text made safe),
how it is called (llama-server, stopping, token counts), and how its answer is checked before anyone
sees it (calculations done by the server, every citation checked against its passage, a playbook's
facts read from its table). No storage, rights or screens: those are the gateway's and the UI's.
"""

from .config import LLMSettings
from .grounding import GROUNDED_INSTRUCTIONS, cited_numbers, grounded_messages
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
    StreamThinking,
    Usage,
)
from .marking import Meaning
from .service import (
    PASSAGES,
    ChatService,
    Delta,
    DocumentsUnavailable,
    Done,
    Retriever,
    Sources,
    Status,
    Thinking,
)
from .usage import Kind, UsageRecord, UsageRecorder

__all__ = [
    "GROUNDED_INSTRUCTIONS",
    "PASSAGES",
    "BackendError",
    "BackendHealth",
    "Calculation",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ChatService",
    "Meaning",
    "Citation",
    "CitationIssue",
    "Delta",
    "DocumentsUnavailable",
    "Done",
    "Kind",
    "LLMSettings",
    "LlamaServerClient",
    "ModelInfo",
    "Retriever",
    "SourceRef",
    "Sources",
    "Status",
    "StreamChunk",
    "StreamDelta",
    "StreamError",
    "StreamSources",
    "StreamStatus",
    "StreamThinking",
    "Thinking",
    "Usage",
    "UsageRecord",
    "UsageRecorder",
    "cited_numbers",
    "grounded_messages",
]
