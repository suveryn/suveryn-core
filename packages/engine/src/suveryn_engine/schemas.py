"""Public request/response shapes for chat completions.

Every answer carries a ``citations`` list from day one. Until RAG is wired in the list is
empty; later each citation's ``source`` points to a page/location in a document, so that no
number or fact is presented without a source. Clients must treat ``source: null`` as
"unsourced" and never as "sourced from nowhere in particular".
"""

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    role: Role
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class SourceRef(BaseModel):
    """Where a cited passage comes from. Populated once document ingestion and RAG exist."""

    document_id: str
    page: int | None = Field(default=None, ge=1, description="1-based page number in the source document")
    location: str | None = Field(default=None, description="Finer position, e.g. article or paragraph number")


class Citation(BaseModel):
    text: str = Field(description="The passage or claim that is being cited")
    source: SourceRef | None = Field(default=None, description="null until RAG supplies a page/location")


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ChatResponse(BaseModel):
    id: str
    model: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage = Field(default_factory=Usage)


class StreamDelta(BaseModel):
    """One streamed chunk of answer text (SSE event ``delta``)."""

    text: str


class StreamError(BaseModel):
    """Sent as SSE event ``error`` when the backend fails mid-stream."""

    message: str
