import pytest
from pydantic import ValidationError
from suveryn_harness import ChatMessage, ChatRequest, ChatResponse, Citation, SourceRef


def test_citations_default_empty():
    r = ChatResponse(id="x", model="m", answer="a")
    assert r.model_dump()["citations"] == []


def test_citation_source_is_nullable_now_and_structured_later():
    unsourced = Citation(text="EUR 230.000,00")
    assert unsourced.model_dump() == {"text": "EUR 230.000,00", "source": None}
    sourced = Citation(text="EUR 230.000,00", source=SourceRef(document_id="doc-1", page=3, location="art. 2"))
    assert sourced.model_dump()["source"] == {"document_id": "doc-1", "page": 3, "location": "art. 2"}


def test_a_conversation_too_long_to_send_is_refused_before_any_work():
    """Audit of 21 October 2026, finding 6: 200 messages of 100,000 characters each were allowed."""
    from suveryn_harness.schemas import MAX_TOTAL_CHARS

    half = "x" * (MAX_TOTAL_CHARS // 2)
    ChatRequest(messages=[ChatMessage(role="user", content=half), ChatMessage(role="assistant", content="ok"),
                          ChatMessage(role="user", content="x" * (MAX_TOTAL_CHARS // 2 - 2))])
    with pytest.raises(ValidationError, match="too long"):
        ChatRequest(messages=[ChatMessage(role="user", content=half), ChatMessage(role="assistant", content=half),
                              ChatMessage(role="user", content="And?")])
