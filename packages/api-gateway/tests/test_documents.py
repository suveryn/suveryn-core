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
from suveryn_harness import Citation, LlamaServerClient, LLMSettings, SourceRef
from suveryn_rag.store import Scope

DOC = str(uuid.uuid4())


class FakeJob:
    def __init__(self, filename, owner="local-dev", case_id=None):
        self.id, self.filename, self.status, self.document_id = uuid.uuid4().hex, filename, "queued", None
        self.owner, self.case_id = owner, case_id

    def public(self):
        return {"id": self.id, "filename": self.filename, "status": self.status, "document_id": self.document_id}


class FakeDocuments:
    """Stands in for suveryn_rag.service.DocumentService, including isolation per scope (a personal
    space or a case, ``suveryn_rag.store.Scope``). ``docs`` maps a document id to its scope and origin."""

    def __init__(self, state="ready", owner="local-dev"):
        self.state, self.error, self.jobs, self.deleted, self.seen, self.uploads = state, None, {}, [], {}, []
        self.docs = {DOC: (Scope.personal(owner), "uploaded")}  # document id -> (scope, origin)
        self.noticed, self.confirmed = {}, {}  # document id -> the mark noticed; -> who confirmed it
        self.uploaders = {}  # document id -> who uploaded it (default local-dev)

    def accept_upload(self, src, filename, owner, case_id=None):
        self.uploads.append((filename, owner, case_id))
        job = FakeJob(filename, owner, case_id)
        self.jobs[job.id] = job
        return job

    def accept_archive(self, src, filename, owner, case_id=None):
        """Two documents and a picture, as the real service would answer for such a zip."""
        self.uploads.append((filename, owner, case_id))
        jobs = [FakeJob(n, owner, case_id) for n in ("akte.pdf", "notes.docx")]
        self.jobs.update({j.id: j for j in jobs})
        return type("A", (), {"jobs": jobs, "public": lambda _: {
            "archive": filename, "jobs": [j.public() for j in jobs], "skipped": [{"name": "photo.jpg", "reason": "unsupported"}]}})()

    def cancel(self, job_id, owner):
        job = self.jobs.get(job_id)
        if job is None or job.owner != owner:
            return None
        if job.status in ("ready", "needs_review", "failed"):
            return False
        job.status = "cancelled"
        return True

    def job(self, job_id, owner):
        job = self.jobs.get(job_id)
        return job if job is not None and job.owner == owner else None

    def pending_jobs(self, owner, scope=None):
        return [j for j in self.jobs.values() if j.owner == owner and j.status in ("queued", "processing", "failed")
                and (scope is None or j.case_id == scope.case_id)]

    def documents(self, scope):
        from datetime import datetime
        return [{"id": uuid.UUID(d), "filename": "akte.pdf", "pages": 5, "ocr_pages": 5, "status": "ok",
                 "warnings": [], "created_at": datetime(2026, 10, 9, tzinfo=UTC), "origin": origin,
                 "uploaded_by": self.uploaders.get(d, "local-dev"),
                 "source": origin == "uploaded" and (d not in self.noticed or d in self.confirmed),
                 "provenance": ({"noticed": self.noticed[d], **({"confirmed": {"by": self.confirmed[d]}} if d in self.confirmed else {})}
                                if d in self.noticed else None)}
                for d, (s, origin) in self.docs.items() if s == scope]

    def documents_many(self, owner, case_ids):
        """The owner's personal documents and every document in ``case_ids``, each with its case id."""
        wanted = [Scope.personal(owner), *(Scope.case(c) for c in case_ids)]
        return [dict(d, case_id=s.case_id) for s in wanted for d in self.documents(s)]

    def in_scope(self, document_ids, scope, sources_only=False):
        return all(d in self.docs and self.docs[d][0] == scope and (not sources_only or (
                   self.docs[d][1] == "uploaded" and (d not in self.noticed or d in self.confirmed))) for d in document_ids)

    def existing(self, document_ids, scope):
        return {d for d in document_ids if d in self.docs and self.docs[d][0] == scope}

    def delete(self, document_id, scope):
        self.deleted.append(document_id)
        if document_id not in self.docs or self.docs[document_id][0] != scope:
            return False
        del self.docs[document_id]
        return True

    def delete_all(self, scope):
        gone = [d for d, (s, _) in self.docs.items() if s == scope]
        for d in gone:
            del self.docs[d]
        return len(gone)

    def retrieve(self, question, document_ids, k, scope):
        assert self.in_scope(document_ids, scope, True), "the gateway must never retrieve documents outside the scope"
        self.seen = {"question": question, "document_ids": document_ids, "k": k, "owner": scope.owner,
                     "case_id": scope.case_id}
        return [(Citation(text="De koopprijs bedraagt EUR 412.500,00.",
                          source=SourceRef(document_id=DOC, page=2, location="p. 2 · Artikel 2")), "akte.pdf")], True

    def withdraw(self, document_id, scope, by, reason=""):
        """A cancelled playbook run's result (docs/design/playbooks.md): marked, never deleted."""
        if document_id not in self.docs or self.docs[document_id][0] != scope or self.docs[document_id][1] == "uploaded":
            return False
        self.withdrawn = {**getattr(self, "withdrawn", {}), document_id: {"by": by, "reason": reason}}
        return True

    def store_text(self, filename, text, scope, origin, provenance=None, content=None, by=None):
        """A playbook's result (suveryn-tracker#51) or a saved answer (docs/design/chat-ui.md §5): stored as a
        document in the scope, never a source."""
        did = str(uuid.uuid4())
        self.docs[did] = (scope, origin)
        self.stored_text = (filename, text)
        self.stored_provenance = provenance
        self.provenances = {**getattr(self, "provenances", {}), did: provenance}
        self.contents = {**getattr(self, "contents", {}), did: (filename, origin, content)}
        if by:
            self.uploaders[did] = by
        return did

    def saved_answer(self, scope, message):
        for did, prov in getattr(self, "provenances", {}).items():
            if did in self.docs and self.docs[did] == (scope, "answer") and (prov or {}).get("message") == message:
                return did, self.contents[did][0]
        return None

    def content(self, document_id, scope):
        found = getattr(self, "contents", {}).get(document_id)
        return found if found and found[2] is not None and self.docs.get(document_id, (None,))[0] == scope else None

    def confirm_source(self, document_id, scope, by):
        """An upload with sūveryn's own export mark, used as a source anyway (docs/design/chat-ui.md §6)."""
        if document_id not in self.noticed or self.docs.get(document_id, (None,))[0] != scope:
            return None
        self.confirmed[document_id] = by
        return self.noticed[document_id]

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
    assert docs.seen == {"question": "Wat is de koopprijs?", "document_ids": [DOC], "k": 6, "owner": "local-dev", "case_id": None}
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
    assert [e for e, _ in events] == ["status", "sources", "status", "delta", "done"]
    # the real steps: the documents are searched, then the model reads the passages it was given
    assert events[0][1]["step"] == "searching"
    assert (events[2][1]["step"], events[2][1]["passages"], events[2][1]["complete"]) == ("reading", 1, True)
    assert events[-1][1]["citations"][0]["source"]["page"] == 2
    # the passages come before the first word, so an answer the person stops keeps its sources
    assert events[1][1]["citations"] == events[-1][1]["citations"]


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
        assert listing["documents"][0]["id"] == DOC and "chunks" not in listing["documents"][0]
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


def test_upload_rejects_other_file_types():
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
        assert not uploads.exists() or not any(uploads.iterdir())  # the rejected upload is not left behind
        r = c.post("/v1/documents", files={"file": ("renamed.docx", io.BytesIO(b"%PDF-1.7"), "application/pdf")})
        assert r.status_code == 415 and "not a valid Word file" in r.json()["detail"]  # the content must fit
        assert not any(uploads.iterdir())
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
    def retrieve(self, question, document_ids, k, scope):
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


def test_an_upload_can_be_cancelled_until_it_is_read():
    """docs/design/chat-ui.md §5: the attachment card's ×. The real queue (no worker: it stays waiting)."""
    import pytest
    pytest.importorskip("suveryn_rag")
    import tempfile
    from pathlib import Path

    from suveryn_rag.config import RagSettings
    from suveryn_rag.service import DocumentService

    svc = DocumentService(RagSettings(work_dir=Path(tempfile.mkdtemp())))
    svc.state = "ready"
    with client(svc) as c:
        job = c.post("/v1/documents", files={"file": ("deed.pdf", io.BytesIO(b"%PDF-1.7 a"), "application/pdf")}).json()
        assert job["progress"] is None and job["error_code"] is None and "cancel_requested" not in job
        assert c.delete(f"/v1/documents/jobs/{job['id']}").status_code == 204
        assert c.get(f"/v1/documents/jobs/{job['id']}").json()["status"] == "cancelled"
        assert c.delete(f"/v1/documents/jobs/{job['id']}").status_code == 204  # again: still cancelled
        assert svc.pending_jobs("local-dev") == []  # not shown as waiting or failed
        assert c.delete("/v1/documents/jobs/nope").status_code == 404


def test_a_read_upload_or_someone_elses_cant_be_cancelled():
    docs = FakeDocuments()
    with client(docs) as c:
        job = c.post("/v1/documents", files={"file": ("deed.pdf", io.BytesIO(b"%PDF-1.7"), "application/pdf")}).json()
        docs.jobs[job["id"]].status = "ready"
        assert c.delete(f"/v1/documents/jobs/{job['id']}").status_code == 409
        docs.jobs[job["id"]].status, docs.jobs[job["id"]].owner = "queued", "someone-else"
        assert c.delete(f"/v1/documents/jobs/{job['id']}").status_code == 404


def test_a_thorough_answer_streams_its_reasoning_apart_from_the_answer():
    """docs/design/chat-ui.md §5: with thinking, the model is told to think, and its reasoning comes as `thinking`
    events, never in a `delta` or the answer."""
    docs, captured = FakeDocuments(), []
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"),
                            transport=llm_transport(captured, text="<think>Article 2 gives the price.</think>The price is EUR 412.500,00 [1]."))
    with TestClient(create_app(llm, documents=docs, load_documents=False, auth=Authenticator.disabled())) as c:
        r = c.post("/v1/chat", json={**ASK, "stream": True, "thinking": True})
    events = [(b.split("\n")[0][7:], json.loads(b.split("\n")[1][6:])) for b in r.text.strip().split("\n\n")]
    kinds = [k for k, _ in events]
    assert "thinking" in kinds and kinds.index("thinking") < kinds.index("delta")
    assert [d["text"] for k, d in events if k == "thinking"] == ["Article 2 gives the price."]
    assert "think" not in "".join(d["text"] for k, d in events if k == "delta")
    done = events[-1][1]
    assert done["reasoning"] == "Article 2 gives the price." and "think" not in done["answer"]
    assert captured[-1]["chat_template_kwargs"] == {"enable_thinking": True}


def test_a_zip_adds_each_document_inside_and_says_what_was_left_out():
    import zipfile

    import pytest
    pytest.importorskip("suveryn_rag")
    import tempfile
    from pathlib import Path

    from suveryn_rag.config import RagSettings
    from suveryn_rag.service import DocumentService

    svc = DocumentService(RagSettings(work_dir=Path(tempfile.mkdtemp())))
    svc.state = "ready"  # no worker: the documents stay queued
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Dossier/akte.pdf", b"%PDF-1.7 a deed")
        z.writestr("Dossier/Prospectus FR.docx", b"PK\x03\x04 a Word file")
        z.writestr("Dossier/photo.jpg", b"\xff\xd8\xff")
        z.writestr("__MACOSX/Dossier/._akte.pdf", b"junk")
    with client(svc) as c:
        r = c.post("/v1/documents", files={"file": ("Dossier.zip", io.BytesIO(buf.getvalue()), "application/zip")})
        assert r.status_code == 202
        body = r.json()
        assert body["archive"] == "Dossier.zip"
        assert sorted(j["filename"] for j in body["jobs"]) == ["Prospectus FR.docx", "akte.pdf"]
        assert all(j["status"] == "queued" for j in body["jobs"])
        assert body["skipped"] == [{"name": "photo.jpg", "reason": "unsupported"}]
        assert c.get(f"/v1/documents/jobs/{body['jobs'][0]['id']}").json()["status"] == "queued"
        stored = sorted(p.suffix for p in (svc.settings.work_dir / "uploads").iterdir())
        assert stored == [".zip"]  # kept until its documents are read, each unpacked in its turn
        r = c.post("/v1/documents", files={"file": ("photos.zip", io.BytesIO(zip_of({"a.jpg": b"\xff\xd8"})), "application/zip")})
        assert r.status_code == 202 and r.json()["jobs"] == []  # nothing to read: each file says why
        assert r.json()["skipped"] == [{"name": "a.jpg", "reason": "unsupported"}]
        r = c.post("/v1/documents", files={"file": ("empty.zip", io.BytesIO(zip_of({})), "application/zip")})
        assert r.status_code == 415 and "empty" in r.json()["detail"]


def zip_of(entries: dict) -> bytes:
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_a_zip_goes_to_the_service_as_an_archive_and_each_document_is_logged():
    docs = FakeDocuments()
    with client(docs) as c:
        r = c.post("/v1/documents", files={"file": ("Dossier.ZIP", io.BytesIO(b"PK\x03\x04"), "application/zip")})
        assert r.status_code == 202 and len(r.json()["jobs"]) == 2 and r.json()["skipped"][0]["reason"] == "unsupported"


def test_an_upload_is_refused_while_the_disk_is_nearly_full(monkeypatch):
    """VM regression of 29 October, finding 5: at 7 % free, Status warned but an upload was still accepted and
    read. Below Status's own limit (a tenth of the disk, or 10 GB) an upload is refused with 507."""
    import tempfile
    from pathlib import Path

    import suveryn_api_gateway.routes.status as status

    docs = FakeDocuments()
    monkeypatch.setattr(status, "DATA_PATH", Path(tempfile.mkdtemp()))  # an appliance's data partition
    monkeypatch.setattr(status, "_disk", lambda: (8 * 1024**3, 155 * 1024**3))  # 8 GB of 155: short
    with client(docs) as c:
        r = c.post("/v1/documents", files={"file": ("deed.pdf", io.BytesIO(b"%PDF-1.7 fictional"), "application/pdf")})
        assert r.status_code == 507 and "nearly full" in r.json()["detail"] and docs.uploads == []
        monkeypatch.setattr(status, "_disk", lambda: (60 * 1024**3, 155 * 1024**3))  # room again
        assert c.post("/v1/documents", files={"file": ("deed.pdf", io.BytesIO(b"%PDF-1.7 fictional"), "application/pdf")}).status_code == 202
