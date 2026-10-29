"""Public request/response shapes for chat completions.

Every answer carries a ``citations`` list. Plain answers have ``citations: []``. Answers to a
request with ``document_ids`` are grounded in retrieved passages (``suveryn_harness``) and carry
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

# All the messages of one request together, in characters (about 37,000 tokens): what a conversation
# may bring along, before the documents' passages are added (up to ``WHOLE_DOCUMENT_CHARS``, 48,000).
# Checked before any search or model call, so an oversized request costs nothing (audit of
# 21 October 2026, finding 6). The UI sends at most ``HISTORY_CHARS`` of earlier turns (lib/history.ts).
MAX_TOTAL_CHARS = 150_000


class ChatMessage(BaseModel):
    """One turn of the conversation, in OpenAI chat format."""

    role: Role
    content: str = Field(max_length=100_000)  # ~25k tokens: more than fits the model's context anyway


class ChatRequest(BaseModel):
    """Body of ``POST /v1/chat``.

    Limits are deliberately bounded: ``max_tokens`` up to 8192 keeps one request from occupying
    the GPU for minutes, and ``temperature`` defaults to 0 because notarial answers should be
    reproducible rather than creative. The last message must be the user's question; the
    conversation is limited to 200 messages, each message to 100,000 characters, and all of them
    together to ``MAX_TOTAL_CHARS``.
    """

    messages: list[ChatMessage] = Field(min_length=1, max_length=200)
    stream: bool = False
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    # Stored documents to answer from. Empty: a plain, unsourced answer. Set: the answer is grounded
    # in passages from these documents and cites them as [n] (see ChatResponse).
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    # The case the documents are in (suveryn-tracker#10). None: the user's personal space. The
    # gateway checks the user may read the case; the documents must all be in it.
    case_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")
    # Which installed model answers (an id from GET /v1/models). None: the appliance's default model.
    model: str | None = Field(default=None, pattern=r"^[\w.:-]{1,120}$")
    # Think before answering (*Thorough*, docs/design/chat-ui.md §5): slower, for a model that can
    # (``ModelInfo.thinks``); ignored for one that can't. False: *Fast*, the appliance's default.
    thinking: bool = False

    @model_validator(mode="after")
    def _ends_with_question(self) -> "ChatRequest":
        if self.messages[-1].role != "user":
            raise ValueError("the last message must be the user's question")
        if sum(len(m.content) for m in self.messages) > MAX_TOTAL_CHARS:
            raise ValueError(f"the conversation is too long to send at once: at most {MAX_TOTAL_CHARS:,} characters")
        return self


class SourceRef(BaseModel):
    """Where a cited passage comes from: a stored document, and a position inside it."""

    document_id: str
    page: int | None = Field(default=None, ge=1, description="1-based page number in the source document")
    location: str | None = Field(default=None, description="Finer position, e.g. 'p. 3-4 · Article 2 - Price', 'Article 2 › Price' or 'Prices!A2:D31'")


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
    thinks: bool = False    # the model family can think before answering: *Thorough* is possible (docs/design/chat-ui.md §5)


class Calculation(BaseModel):
    """A calculation in a grounded answer, computed exactly by the server (``suveryn_harness.calc``).

    The model only chooses the figures; the result is never the model's own arithmetic.
    ``figures_not_in_sources`` lists figures that don't appear (as whole numbers) in the passages
    the answer cites, which a reader should check. ``result`` is None (and ``error`` says why) if it couldn't be computed.
    """

    expression: str
    result: str | None
    figures_not_in_sources: list[str] = Field(default_factory=list)
    error: str | None = None


class CitationIssue(BaseModel):
    """A fact in a cited claim that the cited passage doesn't contain (suveryn-tracker#11).

    ``marker`` is the 0-based occurrence of the marker in ``answer``, counting only markers that refer
    to an existing citation, in text order; ``n`` is its number. ``found_in`` lists other passages that
    do contain ``item``; ``written_as`` is how a passage spells a name the answer spells differently.
    """

    marker: int = Field(ge=0)
    n: int = Field(ge=1)
    item: str
    found_in: list[int] = Field(default_factory=list)
    written_as: str | None = None


class SupportSpan(BaseModel):
    """What the source card marks for one citation marker (suveryn-tracker#25; ``marking.support_spans``).

    ``marker`` is the marker's 0-based occurrence among the answer's valid markers, as ``CitationIssue``
    counts them; ``n`` its number. ``ranges`` are the sentences of ``citations[n - 1].text`` the claim
    rests on, and ``facts`` what to mark strongly: the claim's facts and names, however the passage writes
    them. Both are [start, end) offsets in UTF-16 code units, as the browser counts a string.
    """

    marker: int = Field(ge=0)
    n: int = Field(ge=1)
    ranges: list[tuple[int, int]] = Field(default_factory=list)
    facts: list[tuple[int, int]] = Field(default_factory=list)
    # "words": the sentences share the claim's words and facts; "meaning": the embedding model found the sentence
    # closest in meaning (a paraphrase, another language), which the reader should check (suveryn-tracker#25, step 3).
    how: Literal["words", "meaning"] = "words"


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
    # Grounded answers: figures in the answer text that are in none of the passages and no
    # calculation's result, as the answer writes them. The model worked them out or made them up;
    # clients must flag them for checking.
    unverified_figures: list[str] = Field(default_factory=list)
    # Grounded answers: facts (figures, dates, names) in a cited claim that the passage it cites
    # doesn't contain. Clients must flag the marker, so a reader checks that source.
    citation_issues: list[CitationIssue] = Field(default_factory=list)
    # Grounded answers: per citation marker, what in its passage the claim rests on, for the source card
    # to mark. Computed with the same sentences as ``citation_issues``.
    support_spans: list[SupportSpan] = Field(default_factory=list)
    # Grounded answers: passages (1-based, as the markers) whose text addresses an AI ("ignore the
    # instructions…"). The model was told excerpts are data; clients must still tell the reader.
    instruction_like_sources: list[int] = Field(default_factory=list)
    finish_reason: str | None = None  # "stop"; "length" means the answer was cut off at max_tokens
    usage: Usage = Field(default_factory=Usage)
    # *Thorough*: what the model thought before answering, apart from ``answer`` (never in it), and
    # how long it took. Empty and None for a *Fast* answer.
    reasoning: str = ""
    thought_seconds: float | None = None


class StreamDelta(BaseModel):
    """One streamed chunk of answer text (SSE event ``delta``)."""

    text: str


class StreamThinking(BaseModel):
    """One streamed chunk of the model's reasoning before the answer (SSE event ``thinking``), in
    *Thorough* only. Not part of the answer: it is never in a ``delta``."""

    text: str


class StreamStatus(BaseModel):
    """What the server is doing before the answer's first word (SSE event ``status``).

    Each step is a real stage of the pipeline, so the UI can say so truthfully:
    ``searching`` the documents, ``loading_model`` (a switched-to model is being loaded into the
    GPU), ``reading`` the passages (the model processes them; ``passages``, and ``complete`` when
    they are the documents' whole text), ``writing`` (a plain answer is being prepared), ``thinking``
    (*Thorough*: the model reasons before it answers; its reasoning follows as ``thinking`` events).
    """

    step: Literal["searching", "loading_model", "reading", "writing", "thinking"]
    passages: int | None = None
    complete: bool | None = None
    model: str | None = None


class StreamSources(BaseModel):
    """The passages a grounded answer is written from, sent before its first word (SSE event ``sources``):
    the same list as ``ChatResponse.citations``, so an answer the person stops still shows what its
    markers point to. Not sent for a plain answer."""

    citations: list[Citation]


class StreamError(BaseModel):
    """Sent as SSE event ``error`` when the answer can't be completed: the model backend failed,
    document search is unavailable, or an unexpected server error occurred (reported generically)."""

    message: str
    # What failed, for the page to say in its own language (VM regression of 29 October, finding 14: the
    # message is English and technical): "model", "documents", "document" or "server".
    code: str | None = None
