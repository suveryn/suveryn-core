"""The chat surface: plain answers, or answers grounded in the user's documents.

Conversation state is kept by the client for now (it sends the earlier turns with each request);
nothing about a conversation is stored server-side.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from suveryn_engine import ChatRequest, ChatResponse, Citation, LlamaServerClient, Usage

from .grounding import grounded_messages

# Retrieves passages for a question within the given documents:
# (question, document_ids, k) -> [(citation, filename), ...], best first.
Retriever = Callable[[str, list[str], int], Awaitable[list[tuple[Citation, str]]]]

PASSAGES = 6  # the right passage was in the top 3 for all 19 real-deed questions; 6 leaves margin


@dataclass
class Delta:
    """A piece of answer text as it is generated."""

    text: str


@dataclass
class Done:
    """The complete answer, with its citations."""

    response: ChatResponse


class ChatService:
    """Answers chat requests; grounds them in documents when ``document_ids`` is set.

    Without ``document_ids`` the answer is a plain model answer and its ``citations`` list is
    empty (unsourced). With them, the best passages are retrieved and numbered, the model is told
    to cite them as [n], and ``citations`` holds the passages so that [n] is ``citations[n-1]``.
    """

    def __init__(self, llm: LlamaServerClient, retriever: Retriever | None = None):
        self.llm = llm
        self.retriever = retriever

    async def _prepare(self, req: ChatRequest) -> tuple[ChatRequest, list[Citation]]:
        if not req.document_ids:
            return req, []
        if self.retriever is None:
            raise DocumentsUnavailable("document search is not available on this server")
        *history, last = req.messages
        hits = await self.retriever(last.content, req.document_ids, PASSAGES)
        citations = [c for c, _ in hits]
        messages = grounded_messages(history, last.content, citations, [name for _, name in hits])
        return req.model_copy(update={"messages": messages}), citations

    async def answer(self, req: ChatRequest) -> ChatResponse:
        """Whole answer at once."""
        prepared, citations = await self._prepare(req)
        response = await self.llm.complete(prepared)
        return response.model_copy(update={"citations": citations})

    async def answer_stream(self, req: ChatRequest) -> AsyncIterator[Delta | Done]:
        """Answer text as it is generated, then the complete answer with citations.

        Raises ``BackendError`` (possibly after some deltas) or ``DocumentsUnavailable``.
        """
        prepared, citations = await self._prepare(req)
        parts: list[str] = []
        finish_reason, usage = None, Usage()
        async for chunk in self.llm.stream(prepared):
            if chunk.text:
                parts.append(chunk.text)
                yield Delta(chunk.text)
            finish_reason = chunk.finish_reason or finish_reason
            usage = chunk.usage or usage
        yield Done(ChatResponse(id=f"chat-{uuid.uuid4().hex}", model=await self.llm.model_name(),
                                answer="".join(parts), citations=citations, finish_reason=finish_reason, usage=usage))


class DocumentsUnavailable(RuntimeError):
    """A grounded answer was requested but document search isn't available on this server."""
