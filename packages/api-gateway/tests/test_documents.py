"""Grounded chat and document endpoints, against a fake model server and a fake document service."""

import io
import json
import uuid

import httpx
from fastapi.testclient import TestClient

from suveryn_api_gateway.app import create_app
from suveryn_engine import Citation, LLMSettings, LlamaServerClient, SourceRef

DOC = str(uuid.uuid4())


class FakeJob:
    def __init__(self, filename):
        self.id, self.filename, self.status, self.document_id = uuid.uuid4().hex, filename, "queued", None

    def public(self):
        return {"id": self.id, "filename": self.filename, "status": self.status, "document_id": self.document_id}


class FakeDocuments:
    """Stands in for suveryn_rag.service.DocumentService."""

    def __init__(self, state="ready"):
        self.state, self.error, self.jobs, self.deleted, self.seen = state, None, {}, [], {}

    def accept_upload(self, src, filename):
        from suveryn_rag.service import UploadRejected  # noqa: F401 (only importable with rag installed)

    def job(self, job_id):
        return self.jobs.get(job_id)

    def pending_jobs(self):
        return [j for j in self.jobs.values() if j.status in ("queued", "processing", "failed")]

    def documents(self):
        from datetime import datetime, timezone
        return [{"id": uuid.UUID(DOC), "filename": "akte.pdf", "pages": 5, "ocr_pages": 5, "status": "ok",
                 "warnings": [], "created_at": datetime(2026, 10, 9, tzinfo=timezone.utc), "chunks": 12}]

    def delete(self, document_id):
        self.deleted.append(document_id)
        return document_id == DOC

    def retrieve(self, question, document_ids, k):
        self.seen = {"question": question, "document_ids": document_ids, "k": k}
        return [(Citation(text="De koopprijs bedraagt EUR 412.500,00.",
                          source=SourceRef(document_id=DOC, page=2, location="p. 2 · Artikel 2")), "akte.pdf")]

    def stop(self):
        pass


def llm_transport(captured):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "Qwen3.8-27B-UD-Q4_K_M.gguf"}]})
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        body = json.loads(request.content)
        captured.append(body)
        text = "De koopprijs is EUR 412.500,00 [1]."
        if body["stream"]:
            sse = "".join(f"data: {json.dumps(c)}\n\n" for c in [
                {"choices": [{"delta": {"content": text}, "finish_reason": None}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]}]) + "data: [DONE]\n\n"
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"id": "x", "choices": [{"message": {"content": text}, "finish_reason": "stop"}]})
    return httpx.MockTransport(handler)


def client(docs, captured=None):
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport(captured if captured is not None else []))
    return TestClient(create_app(llm, documents=docs, load_documents=False))


ASK = {"messages": [{"role": "user", "content": "Wat is de koopprijs?"}], "document_ids": [DOC]}


def test_grounded_answer_carries_citations_and_prompt_has_question_last():
    docs, captured = FakeDocuments(), []
    with client(docs, captured) as c:
        r = c.post("/v1/chat", json=ASK)
    assert r.status_code == 200
    body = r.json()
    assert body["answer"].endswith("[1].")
    assert body["citations"][0]["source"] == {"document_id": DOC, "page": 2, "location": "p. 2 · Artikel 2"}
    assert docs.seen == {"question": "Wat is de koopprijs?", "document_ids": [DOC], "k": 6}
    sent = captured[-1]["messages"]
    assert sent[0]["role"] == "system" and sent[-1]["content"].endswith("QUESTION: Wat is de koopprijs?")
    assert "document_ids" not in captured[-1]  # never forwarded to the model server


def test_grounded_stream_ends_with_done_including_citations():
    with client(FakeDocuments()) as c, c.stream("POST", "/v1/chat", json={**ASK, "stream": True}) as r:
        blocks = r.read().decode().strip().split("\n\n")
    events = [(b.split("\n")[0][7:], json.loads(b.split("\n")[1][6:])) for b in blocks]
    assert [e for e, _ in events] == ["delta", "done"]
    assert events[-1][1]["citations"][0]["source"]["page"] == 2


def test_plain_chat_without_documents_is_unsourced():
    with client(FakeDocuments()) as c:
        r = c.post("/v1/chat", json={"messages": [{"role": "user", "content": "Hallo"}]})
    assert r.json()["citations"] == []


def test_grounded_chat_when_documents_unavailable_is_503():
    with client(None) as c:
        assert c.post("/v1/chat", json=ASK).status_code == 503
        with c.stream("POST", "/v1/chat", json={**ASK, "stream": True}) as r:
            assert r.read().decode().startswith("event: error")


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
    from suveryn_rag.config import RagSettings
    from suveryn_rag.service import DocumentService
    import tempfile
    from pathlib import Path

    svc = DocumentService(RagSettings(work_dir=Path(tempfile.mkdtemp())))
    svc.state = "ready"  # don't load models; only the upload path is exercised
    with client(svc) as c:
        r = c.post("/v1/documents", files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")})
        assert r.status_code == 415
        uploads = svc.settings.work_dir / "uploads"
        assert not any(uploads.iterdir())  # the rejected upload is not left behind
    assert not uploads.exists()  # and the upload folder is removed on shutdown
