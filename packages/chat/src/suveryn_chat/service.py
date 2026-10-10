"""The chat surface: plain answers, or answers grounded in the user's documents.

Conversation state is kept by the client for now (it sends the earlier turns with each request);
nothing about a conversation is stored server-side.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from suveryn_engine import BackendError, ChatRequest, ChatResponse, Citation, LlamaServerClient, Usage

from .calc import CalcRewriter, rewrite
from .grounding import cited_numbers, grounded_messages

# Passages to answer a question from, within the given documents of one user:
# (question, document_ids, k, owner) -> ([(citation, filename), ...], complete). The retriever must
# refuse documents that don't belong to ``owner``. ``complete`` is True when
# the passages are the documents' whole text in reading order (small documents), False when they
# are a selection: the best-matching passages that fit the whole-document budget, at least ``k``.
Retriever = Callable[[str, list[str], int, str], Awaitable[tuple[list[tuple[Citation, str]], bool]]]

# The fewest passages a larger document gives (the budget usually allows far more): the right passage
# was in the top 3 for all 19 real-deed questions.
PASSAGES = 6


@dataclass
class Delta:
    """A piece of answer text as it is generated."""

    text: str


@dataclass
class Status:
    """A pipeline step before the first word (see ``StreamStatus``)."""

    step: str
    passages: int | None = None
    complete: bool | None = None
    model: str | None = None


@dataclass
class Done:
    """The complete answer, with its citations."""

    response: ChatResponse


class ChatService:
    """Answers chat requests; grounds them in documents when ``document_ids`` is set.

    Without ``document_ids`` the answer is a plain model answer and its ``citations`` list is
    empty (unsourced). With them, the documents' passages (all of them for small documents, else
    the best search hits) are numbered, the model is told to cite them as [n], and ``citations``
    holds the passages so that [n] is ``citations[n-1]``.
    """

    def __init__(self, llm: LlamaServerClient, retriever: Retriever | None = None):
        self.llm = llm
        self.retriever = retriever

    async def _retrieve(self, req: ChatRequest, owner: str) -> tuple[ChatRequest, list[Citation], bool]:
        """The grounded request, its passages, and whether they are the documents' complete text."""
        if not req.document_ids:
            return req, [], False
        if self.retriever is None:
            raise DocumentsUnavailable("document search is not available on this server")
        *history, last = req.messages
        hits, complete = await self.retriever(last.content, req.document_ids, PASSAGES, owner)
        citations = [c for c, _ in hits]
        messages = grounded_messages(history, last.content, citations, [name for _, name in hits], complete)
        return req.model_copy(update={"messages": messages}), citations, complete

    async def _prepare(self, req: ChatRequest, owner: str) -> tuple[ChatRequest, list[Citation]]:
        prepared, citations, _ = await self._retrieve(req, owner)
        return prepared, citations

    async def _model_to_load(self, req: ChatRequest) -> str | None:
        """The model that must be loaded before this answer can start, or None if it is loaded."""
        try:
            models = await self.llm.list_models()
        except BackendError:
            return None  # the request itself will report the problem
        wanted = req.model or self.llm.settings.default_model
        for m in models:
            if m.id == wanted:
                return None if m.loaded else m.id
        return None

    async def answer(self, req: ChatRequest, owner: str) -> ChatResponse:
        """Whole answer at once, grounded only in ``owner``'s documents."""
        prepared, citations = await self._prepare(req, owner)
        response = await self.llm.complete(prepared)
        if not req.document_ids:
            return response
        # Replacing calculations leaves the [n] markers as they are, so the cited passages are known up front.
        text, calculations = rewrite(response.answer, _source(citations), _cited_sources(response.answer, citations))
        return response.model_copy(update={"answer": text, "citations": citations, "calculations": calculations})

    async def answer_stream(self, req: ChatRequest, owner: str) -> AsyncIterator[Status | Delta | Done]:
        """Status steps, then answer text as it is generated, then the complete answer with citations.

        Status steps are the pipeline's real stages, so a UI can say what is happening: searching
        the documents, loading a model, reading the passages or writing. Raises ``BackendError``
        (possibly after some deltas) or ``DocumentsUnavailable``.
        """
        if req.document_ids:
            yield Status("searching")
        prepared, citations, complete = await self._retrieve(req, owner)
        if loading := await self._model_to_load(req):
            yield Status("loading_model", model=loading)
        elif req.document_ids:
            yield Status("reading", passages=len(citations), complete=complete)
        else:
            yield Status("writing")
        # Grounded answers: calculation markers are replaced as they stream (see ``calc``).
        calc = CalcRewriter(_source(citations)) if req.document_ids else None
        parts: list[str] = []
        finish_reason, usage = None, Usage()
        async for chunk in self.llm.stream(prepared):
            text = calc.feed(chunk.text) if calc and chunk.text else chunk.text
            if text:
                parts.append(text)
                yield Delta(text)
            finish_reason = chunk.finish_reason or finish_reason
            usage = chunk.usage or usage
        if calc and (rest := calc.flush()):
            parts.append(rest)
            yield Delta(rest)
        answer = "".join(parts)
        calculations = calc.check_figures(_cited_sources(answer, citations)) if calc else []
        yield Done(ChatResponse(id=f"chat-{uuid.uuid4().hex}", model=await self.llm.model_name(req.model), answer=answer,
                                citations=citations, calculations=calculations, finish_reason=finish_reason, usage=usage))


def _source(citations: list[Citation]) -> str:
    """All passages' text (sets the decimal style of whole-number calculation results)."""
    return "\n".join(c.text for c in citations)


def _cited_sources(answer: str, citations: list[Citation]) -> list[str]:
    """The text of the passages the answer cites, which calculation figures are checked against."""
    return [citations[n - 1].text for n in cited_numbers(answer, len(citations))]


class DocumentsUnavailable(RuntimeError):
    """A grounded answer was requested but document search isn't available on this server."""
