"""Grounded chat and document endpoints, against a fake model server and a fake document service."""

import io
import json
import uuid
from datetime import UTC

import httpx
import pytest
from fastapi.testclient import TestClient
from suveryn_api_gateway.app import create_app
from suveryn_api_gateway.auth import Authenticator
from suveryn_engine import Citation, LlamaServerClient, LLMSettings, SourceRef

DOC = str(uuid.uuid4())


class FakeJob:
    def __init__(self, filename, owner="local-dev"):
        self.id, self.filename, self.status, self.document_id = uuid.uuid4().hex, filename, "queued", None
        self.owner = owner

    def public(self):
        return {"id": self.id, "filename": self.filename, "status": self.status, "document_id": self.document_id}


class FakeDocuments:
    """Stands in for suveryn_rag.service.DocumentService, including per-owner isolation."""

    def __init__(self, state="ready", owner="local-dev"):
        self.state, self.error, self.jobs, self.deleted, self.seen, self.uploads = state, None, {}, [], {}, []
        self.docs = {DOC: owner}  # document id -> owner

    def accept_upload(self, src, filename, owner):
        self.uploads.append((filename, owner))
        from suveryn_rag.service import (
            UploadRejected,  # noqa: F401 (only importable with rag installed)
        )

    def job(self, job_id, owner):
        job = self.jobs.get(job_id)
        return job if job is not None and job.owner == owner else None

    def pending_jobs(self, owner):
        return [j for j in self.jobs.values() if j.owner == owner and j.status in ("queued", "processing", "failed")]

    def documents(self, owner):
        from datetime import datetime
        return [{"id": uuid.UUID(d), "filename": "akte.pdf", "pages": 5, "ocr_pages": 5, "status": "ok",
                 "warnings": [], "created_at": datetime(2026, 10, 9, tzinfo=UTC), "chunks": 12}
                for d, o in self.docs.items() if o == owner]

    def owns(self, document_ids, owner):
        return all(self.docs.get(d) == owner for d in document_ids)

    def delete(self, document_id, owner):
        self.deleted.append(document_id)
        if self.docs.get(document_id) != owner:
            return False
        del self.docs[document_id]
        return True

    def retrieve(self, question, document_ids, k, owner):
        assert self.owns(document_ids, owner), "the gateway must never retrieve another owner's documents"
        self.seen = {"question": question, "document_ids": document_ids, "k": k, "owner": owner}
        return [(Citation(text="De koopprijs bedraagt EUR 412.500,00.",
                          source=SourceRef(document_id=DOC, page=2, location="p. 2 · Artikel 2")), "akte.pdf")], True

    def stop(self):
        pass


def llm_transport(captured, text="De koopprijs is EUR 412.500,00 [1].", usage: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "Qwen3.8-27B-UD-Q4_K_M.gguf"}]})
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/models":  # a single-model llama-server has no router endpoint
            return httpx.Response(404)
        body = json.loads(request.content)
        captured.append(body)
        if body["stream"]:
            sse = "".join(f"data: {json.dumps(c)}\n\n" for c in [
                {"choices": [{"delta": {"content": text}, "finish_reason": None}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                *([{"choices": [], "usage": usage}] if usage else [])]) + "data: [DONE]\n\n"
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"id": "x", "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                                         **({"usage": usage} if usage else {})})
    return httpx.MockTransport(handler)


def client(docs, captured=None):
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport(captured if captured is not None else []))
    return TestClient(create_app(llm, documents=docs, load_documents=False, auth=Authenticator.disabled()))


ASK = {"messages": [{"role": "user", "content": "Wat is de koopprijs?"}], "document_ids": [DOC]}


def test_grounded_answer_carries_citations_and_prompt_has_question_last():
    docs, captured = FakeDocuments(), []
    with client(docs, captured) as c:
        r = c.post("/v1/chat", json=ASK)
    assert r.status_code == 200
    body = r.json()
    assert body["answer"].endswith("[1].")
    assert body["citations"][0]["source"] == {"document_id": DOC, "page": 2, "location": "p. 2 · Artikel 2"}
    assert docs.seen == {"question": "Wat is de koopprijs?", "document_ids": [DOC], "k": 6, "owner": "local-dev"}
    sent = captured[-1]["messages"]
    assert sent[0]["role"] == "system" and sent[-1]["content"].endswith("QUESTION: Wat is de koopprijs?")
    assert sent[-1]["content"].startswith("EXCERPTS (the complete text of the documents")
    assert "document_ids" not in captured[-1]  # never forwarded to the model server


def test_follow_up_searches_with_the_question_before_it():
    """"bereken die" names nothing to search for; the earlier question brings its subject along."""
    docs, captured = FakeDocuments(), []
    follow_up = {"messages": [{"role": "user", "content": "Wat zijn de schattingsbedragen?"},
                              {"role": "assistant", "content": "Kavel 1: EUR 412.500,00."},
                              {"role": "user", "content": "bereken die"}], "document_ids": [DOC]}
    with client(docs, captured) as c:
        assert c.post("/v1/chat", json=follow_up).status_code == 200
    assert docs.seen["question"] == "Wat zijn de schattingsbedragen?\nbereken die"
    assert captured[-1]["messages"][-1]["content"].endswith("QUESTION: bereken die")  # the model gets the question as asked


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("answer, shown, missing", [
    # The model cited nothing: the system adds the passage that holds the figures.
    ("Samen [[calc: 412.500,00 + 412.500,00]] EUR.", "412.500,00 + 412.500,00 = 825.000,00 [1] EUR.", []),
    # Already cited: nothing is added.
    ("Samen [[calc: 412.500,00 + 412.500,00]] EUR [1].", "412.500,00 + 412.500,00 = 825.000,00 EUR [1].", []),
    # An invented figure gets no source and is still reported; the real one gets its source.
    ("Samen [[calc: 412.500,00 + 999,00]] EUR.", "412.500,00 + 999,00 = 413.499,00 [1] EUR.", ["999,00"]),
    ("Samen [[calc: 999,00 + 1.000,00]] EUR.", "999,00 + 1.000,00 = 1.999,00 EUR.", ["999,00", "1.000,00"]),
])
def test_calculation_figures_are_cited_by_the_system_when_the_model_did_not(answer, shown, missing, stream):
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([], text=answer))
    with TestClient(create_app(llm, documents=FakeDocuments(), load_documents=False, auth=Authenticator.disabled())) as c:
        if stream:
            with c.stream("POST", "/v1/chat", json={**ASK, "stream": True}) as r:
                lines = [ln for ln in r.iter_lines() if ln.startswith("data:")]
            body = json.loads(lines[-1][5:])  # the done event
        else:
            body = c.post("/v1/chat", json=ASK).json()
    assert body["answer"] == "Samen " + shown
    assert body["calculations"][0]["figures_not_in_sources"] == missing


@pytest.mark.parametrize("stream", [False, True])
def test_figures_the_model_worked_out_itself_are_flagged(stream):
    answer = "De koopprijs is EUR 412.500 [1]; met kosten 451.000,00 EUR."
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([], text=answer))
    with TestClient(create_app(llm, documents=FakeDocuments(), load_documents=False, auth=Authenticator.disabled())) as c:
        if stream:
            with c.stream("POST", "/v1/chat", json={**ASK, "stream": True}) as r:
                body = json.loads([ln for ln in r.iter_lines() if ln.startswith("data:")][-1][5:])
        else:
            body = c.post("/v1/chat", json=ASK).json()
    assert body["unverified_figures"] == ["451.000,00"]  # 412.500 is the passage's 412.500,00


def test_grounded_stream_ends_with_done_including_citations():
    with client(FakeDocuments()) as c, c.stream("POST", "/v1/chat", json={**ASK, "stream": True}) as r:
        blocks = r.read().decode().strip().split("\n\n")
    events = [(b.split("\n")[0][7:], json.loads(b.split("\n")[1][6:])) for b in blocks]
    assert [e for e, _ in events] == ["status", "status", "delta", "done"]
    # the real steps: the documents are searched, then the model reads the passages it was given
    assert events[0][1]["step"] == "searching"
    assert (events[1][1]["step"], events[1][1]["passages"], events[1][1]["complete"]) == ("reading", 1, True)
    assert events[-1][1]["citations"][0]["source"]["page"] == 2


def test_plain_chat_without_documents_is_unsourced():
    with client(FakeDocuments()) as c:
        r = c.post("/v1/chat", json={"messages": [{"role": "user", "content": "Hallo"}]})
    assert r.json()["citations"] == []


def test_grounded_chat_when_documents_unavailable_is_503():
    with client(None) as c:
        assert c.post("/v1/chat", json=ASK).status_code == 503
        # streamed too: the ownership check runs before the stream starts, so it's a plain 503
        assert c.post("/v1/chat", json={**ASK, "stream": True}).status_code == 503


def test_bad_document_id_is_422():
    with client(FakeDocuments()) as c:
        assert c.post("/v1/chat", json={**ASK, "document_ids": ["../etc"]}).status_code == 422


def test_documents_list_and_delete():
    docs = FakeDocuments()
    with client(docs) as c:
        listing = c.get("/v1/documents").json()
        assert listing["documents"][0]["id"] == DOC and listing["documents"][0]["chunks"] == 12
        assert c.delete(f"/v1/documents/{DOC}").status_code == 204
        assert c.delete(f"/v1/documents/{uuid.uuid4()}").status_code == 404
        assert c.delete("/v1/documents/not-an-id").status_code == 422


def test_document_endpoints_503_when_unavailable_or_starting():
    with client(None) as c:
        assert c.get("/v1/documents").status_code == 503
        assert c.get("/health").json()["documents"]["status"] == "unavailable"
    with client(FakeDocuments(state="starting")) as c:
        assert c.get("/v1/documents").status_code == 503
        assert c.get("/health").json()["documents"]["status"] == "starting"


def test_upload_rejects_non_pdf():
    import pytest
    pytest.importorskip("suveryn_rag")
    import tempfile
    from pathlib import Path

    from suveryn_rag.config import RagSettings
    from suveryn_rag.service import DocumentService

    svc = DocumentService(RagSettings(work_dir=Path(tempfile.mkdtemp())))
    svc.state = "ready"  # don't load models; only the upload path is exercised
    with client(svc) as c:
        r = c.post("/v1/documents", files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")})
        assert r.status_code == 415
        uploads = svc.settings.work_dir / "uploads"
        assert not any(uploads.iterdir())  # the rejected upload is not left behind
    assert not uploads.exists()  # and the upload folder is removed on shutdown


def test_oversized_upload_is_refused_before_its_body_is_read():
    from suveryn_api_gateway.app import MAX_UPLOAD_BYTES

    docs = FakeDocuments()
    with client(docs) as c:
        r = c.post("/v1/documents", content=b"%PDF-", headers={"content-length": str(MAX_UPLOAD_BYTES * 2),
                                                                  "content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 413 and docs.uploads == []


def test_last_message_must_be_the_question():
    with client(FakeDocuments()) as c:
        r = c.post("/v1/chat", json={"messages": [{"role": "user", "content": "Vraag"},
                                                  {"role": "assistant", "content": "Antwoord"}]})
    assert r.status_code == 422


class BrokenDocuments(FakeDocuments):
    def retrieve(self, question, document_ids, k, owner):
        raise RuntimeError("De koopprijs bedraagt EUR 412.500,00")  # an error message holding document text


def test_unexpected_stream_error_is_generic_and_does_not_echo_content():
    with client(BrokenDocuments()) as c, c.stream("POST", "/v1/chat", json={**ASK, "stream": True}) as r:
        body = r.read().decode()
    assert body.startswith("event: status") and "412.500" not in body
    assert body.rstrip().split("\n\n")[-1].startswith("event: error")


class UnreachableDatabase(FakeDocuments):
    def documents(self, owner):
        from suveryn_api_gateway.app import SearchUnavailable
        raise SearchUnavailable("the document database can't be reached")


def test_database_unreachable_is_503():
    with client(UnreachableDatabase()) as c:
        assert c.get("/v1/documents").status_code == 503
