from suveryn_engine import ChatResponse, Citation, SourceRef


def test_citations_default_empty():
    r = ChatResponse(id="x", model="m", answer="a")
    assert r.model_dump()["citations"] == []


def test_citation_source_is_nullable_now_and_structured_later():
    unsourced = Citation(text="EUR 230.000,00")
    assert unsourced.model_dump() == {"text": "EUR 230.000,00", "source": None}
    sourced = Citation(text="EUR 230.000,00", source=SourceRef(document_id="doc-1", page=3, location="art. 2"))
    assert sourced.model_dump()["source"] == {"document_id": "doc-1", "page": 3, "location": "art. 2"}
