"""Public request/response shapes for chat completions.

Every answer carries a ``citations`` list. Plain answers have ``citations: []``. Answers to a
request with ``document_ids`` are grounded in retrieved passages (``suveryn_chat``) and carry
those passages as citations with ``source`` filled in (document, page, location).

Review invariant: clients must treat ``source: null`` (and an empty ``citations`` list) as
"unsourced" and show the answer as unverified. A number or fact without a source must never be
presented as established: in the hardware benchmark the model miscalculated a figure once and
misspelled names it had read correctly
(https://github.com/suveryn/suveryn-docs/blob/main/benchmarks/2026-10-hardware-benchmark.md).
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Role = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    """One turn of the conversation, in OpenAI chat format."""

    role: Role
    content: str = Field(max_length=100_000)  # ~25k tokens: more than fits the model's context anyway


class ChatRequest(BaseModel):
    """Body of ``POST /v1/chat``.

    Limits are deliberately bounded: ``max_tokens`` up to 8192 keeps one request from occupying
    the GPU for minutes, and ``temperature`` defaults to 0 because notarial answers should be
    reproducible rather than creative. The last message must be the user's question; the
    conversation is limited to 200 messages and each message to 100,000 characters.
    """

    messages: list[ChatMessage] = Field(min_length=1, max_length=200)
    stream: bool = False
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    # Stored documents to answer from. Empty: a plain, unsourced answer. Set: the answer is grounded
    # in passages from these documents and cites them as [n] (see ChatResponse).
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    # Which installed model answers (an id from GET /v1/models). None: the appliance's default model.
    model: str | None = Field(default=None, pattern=r"^[\w.:-]{1,120}$")

    @model_validator(mode="after")
    def _ends_with_question(self) -> "ChatRequest":
        if self.messages[-1].role != "user":
            raise ValueError("the last message must be the user's question")
        return self


class SourceRef(BaseModel):
    """Where a cited passage comes from: a stored document, and a position inside it."""

    document_id: str
    page: int | None = Field(default=None, ge=1, description="1-based page number in the source document")
    location: str | None = Field(default=None, description="Finer position, e.g. 'p. 3-4 · Artikel 2 - Koopprijs'")


class Citation(BaseModel):
    """A passage the answer relies on. ``source`` is null when the passage can't be traced to a document."""

    text: str = Field(description="The passage or claim that is being cited")
    source: SourceRef | None = Field(default=None, description="null means unsourced; show as unverified")


class Usage(BaseModel):
    """Token counts reported by the model server, for capacity monitoring (no content)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0


class ModelInfo(BaseModel):
    """An installed model, as listed by ``GET /v1/models``."""

    id: str                 # what to send as ``ChatRequest.model``
    loaded: bool            # in GPU memory now; otherwise the first answer waits for it to load
    default: bool = False   # the appliance's default model


class Calculation(BaseModel):
    """A calculation in a grounded answer, computed exactly by the server (``suveryn_chat.calc``).

    The model only chooses the figures; the result is never the model's own arithmetic.
    ``figures_not_in_sources`` lists figures that don't appear (as whole numbers) in the passages
    the answer cites, which a reader should check. ``result`` is None (and ``error`` says why) if it couldn't be computed.
    """

    expression: str
    result: str | None
    figures_not_in_sources: list[str] = Field(default_factory=list)
    error: str | None = None


class ChatResponse(BaseModel):
    """A complete answer. Returned as JSON, or as the final ``done`` event of a stream.

    ``model`` is the model file llama-server reports (e.g. ``Qwen3.8-27B-UD-Q4_K_M.gguf``), so a
    reviewer can always tell which model produced an answer.

    Citation contract: in a grounded answer, the marker ``[n]`` in ``answer`` refers to
    ``citations[n - 1]``. ``citations`` holds every passage the model was given, in that order;
    a passage the answer never cites is still listed, so clients show only the cited ones.
    """

    id: str
    model: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    calculations: list[Calculation] = Field(default_factory=list)  # in the order they appear in ``answer``
    finish_reason: str | None = None  # "stop"; "length" means the answer was cut off at max_tokens
    usage: Usage = Field(default_factory=Usage)


class StreamDelta(BaseModel):
    """One streamed chunk of answer text (SSE event ``delta``)."""

    text: str


class StreamError(BaseModel):
    """Sent as SSE event ``error`` when the answer can't be completed: the model backend failed,
    document search is unavailable, or an unexpected server error occurred (reported generically)."""

    message: str
