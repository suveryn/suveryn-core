"""The focus flag reaches the retriever only for a case's sources (ChatRequest.focus)."""

import asyncio

from suveryn_harness import ChatRequest, ChatService, Citation, SourceRef

CASE = "00000000-0000-0000-0000-000000000001"


def retrieve_with(**request):
    seen = {}

    async def retriever(question, document_ids, k, owner, case_id=None, **kw):
        seen.update(kw, case_id=case_id)
        return [(Citation(text="A passage.", source=SourceRef(document_id=document_ids[0], page=1)), "deed.pdf")], True

    service = ChatService(llm=None, retriever=retriever)
    req = ChatRequest(messages=[{"role": "user", "content": "What is the price?"}], document_ids=["d1", "d2"], **request)
    asyncio.run(service._retrieve(req, "user-a"))
    return seen


def test_focus_is_passed_for_a_cases_sources_only():
    assert retrieve_with(case_id=CASE, focus=True) == {"focus": True, "case_id": CASE}
    assert retrieve_with(case_id=CASE) == {"case_id": CASE}            # attached documents: as before
    assert retrieve_with(focus=True) == {"case_id": None}              # personal space: nothing to narrow


def test_a_retriever_without_focus_still_works_for_chosen_documents():
    async def old(question, document_ids, k, owner, case_id=None):
        return [], True

    req = ChatRequest(messages=[{"role": "user", "content": "Price?"}], document_ids=["d1"], case_id=CASE)
    asyncio.run(ChatService(llm=None, retriever=old)._retrieve(req, "user-a"))
