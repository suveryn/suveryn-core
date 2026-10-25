"""Playbook runs (suveryn-tracker#51): deed intake read from a case's documents, checked at the
checkpoint, stored as a document with origin ``playbook``. Design: docs/design/playbooks.md.
Reading the model's table is the harness's and tested there (packages/harness/tests/test_facts.py)."""

import os
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from suveryn_api_gateway.app import create_app
from suveryn_api_gateway.auth import Authenticator, OIDCProvider
from suveryn_api_gateway.cases import CaseSettings
from suveryn_api_gateway.playbooks import RunStore, summary_text
from suveryn_harness import LlamaServerClient, LLMSettings
from suveryn_harness.facts import read_facts
from suveryn_playbooks import DEED_INTAKE
from suveryn_rag.store import Scope
from test_auth import SETTINGS, FakeKeycloak
from test_cases import ALICE, BOB, NEW, FakeCases, FakeDirectory, admin_headers
from test_conversations import FakeConversations, as_user
from test_documents import DOC, FakeDocuments, llm_transport

# The model's table for deed intake and its passages: the harness's own test fixtures (reading the table is the harness's).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness" / "tests"))
from test_facts import DOC as TABLE_DOC
from test_facts import TABLE, response


def test_summary_text_uses_the_confirmed_values_and_the_language():
    from suveryn_api_gateway.playbooks import Run
    facts = read_facts(DEED_INTAKE, response(), {TABLE_DOC: "compromis.pdf"})
    for f in facts:
        f.confirmed = "EUR 412.000,00" if f.id == "price" else f.value
    run = Run(id=str(uuid.uuid4()), case_id=str(uuid.uuid4()), playbook_id=DEED_INTAKE.id, playbook_version="1.0",
              status="confirmed", documents=[DOC], started_by=ALICE, started_at="2026-10-17T10:00:00Z", facts=facts)
    # the title and labels are the playbook's own words in that language (suveryn_playbooks, docs/translations.md)
    text = summary_text(DEED_INTAKE, "2026/0417", run, "fr")
    assert text.startswith("Intake de l'acte 2026/0417\n\nplaybook/be-notary/deed-intake 1.0")
    assert "Prix: EUR 412.000,00 (compromis.pdf p. 1)" in text and "Données cadastrales: —" in text
    assert summary_text(DEED_INTAKE, "2026/0417", run, "de").startswith("Deed intake 2026/0417")  # unknown: English
    # provenance (review 2026-10-17): the run's version, not the playbook's as installed now
    older = run.model_copy(update={"playbook_version": "0.9"})
    assert "playbook/be-notary/deed-intake 0.9" in summary_text(DEED_INTAKE, "2026/0417", older, "en")


# ------------------------------------------------------------------ through the app (needs PostgreSQL for the runs)

URL = os.environ.get("SUVERYN_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not URL, reason="SUVERYN_TEST_DATABASE_URL not set")


@pytest.fixture
def runs():
    s = RunStore(URL)
    yield s
    s._execute("DELETE FROM playbook_runs WHERE started_by IN (%s, %s, %s)", (ALICE, BOB, "notaris.test"))
    s._execute("DELETE FROM playbook_settings", ())
    s.close()


@pytest.fixture
def office(runs):
    kc, cases, history, docs = FakeKeycloak(), FakeCases(), FakeConversations(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    captured = []
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport(captured, text=TABLE))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=history, cases=cases, runs=runs,
                     case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    with TestClient(app) as c:
        yield c, kc, cases, docs, captured


def wait_for(c, url, headers, status, tries=50):
    for _ in range(tries):
        run = c.get(url, headers=headers).json()
        if run["status"] == status:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run never reached {status}: {run['status']}")


@needs_db
def test_deed_intake_reads_the_case_checks_the_facts_and_stores_the_summary(office):
    c, kc, _, docs, captured = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "reader"}, headers=alice)
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    docs.docs[str(uuid.uuid4())] = (Scope.case(uuid.UUID(cid)), "playbook")  # an earlier result: never read
    # which playbooks fit: a sale gets deed intake, covered
    fits = c.get(f"/v1/cases/{cid}/playbooks", headers=bob).json()
    assert [(p["id"], p["covered"], p["version"]) for p in fits] == [("playbook/be-notary/deed-intake", True, "1.0")]
    # the playbook's own words, in every interface language (docs/translations.md)
    assert set(fits[0]["text"]) == {"en", "nl", "fr"} and fits[0]["text"]["en"]["title"] == "Deed intake"
    assert fits[0]["text"]["en"]["labels"]["price"] == "Price"
    # a reader can't start; a contributor can, and the run reads only the uploaded document
    assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=bob).status_code == 403
    assert c.post(f"/v1/cases/{cid}/playbooks/estate-intake/runs", json={}, headers=alice).status_code == 404
    r = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice)
    assert r.status_code == 202 and r.json()["status"] == "reading" and r.json()["documents"] == [DOC]
    assert r.json()["playbook_id"] == "playbook/be-notary/deed-intake" and r.json()["playbook_version"] == "1.0"
    rid = r.json()["id"]
    run = wait_for(c, f"/v1/cases/{cid}/playbooks/runs/{rid}", bob, "checkpoint")
    assert "| sellers | | |" in captured[-1]["messages"][-1]["content"]  # the playbook's instructions went to the model
    by = {f["id"]: f for f in run["facts"]}
    assert by["price"]["value"] == "EUR 412.500,00" and by["price"]["citations"][0]["filename"] == "akte.pdf"
    assert run["model"] == "Qwen3.8-27B-UD-Q4_K_M.gguf" and by["cadastral"]["found"] is False
    assert [x["id"] for x in c.get(f"/v1/cases/{cid}/playbooks/runs", headers=bob).json()] == [rid]
    # the checkpoint: a reader can't confirm; the contributor corrects the price and confirms the rest
    confirm = {"facts": [{"id": "price", "confirmed": "EUR 412.000,00"}, {"id": "cadastral", "confirmed": "Gent 5e afd., sectie B, nr. 123"}],
               "language": "en"}
    assert c.put(f"/v1/cases/{cid}/playbooks/runs/{rid}/facts", json=confirm, headers=bob).status_code == 403
    assert c.put(f"/v1/cases/{cid}/playbooks/runs/{rid}/facts", json={"facts": [{"id": "x", "confirmed": ""}]}, headers=alice).status_code == 422
    r = c.put(f"/v1/cases/{cid}/playbooks/runs/{rid}/facts", json=confirm, headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "confirmed" and r.json()["confirmed_by"] == "notaris.test"
    by = {f["id"]: f for f in r.json()["facts"]}
    assert by["price"]["confirmed"] == "EUR 412.000,00" and by["price"]["value"] == "EUR 412.500,00"
    assert by["sellers"]["confirmed"] == "Jan Peeters en Marie Claes" and by["cadastral"]["confirmed"].startswith("Gent")
    # the summary is a document in the case with origin playbook, named after the playbook and the case
    name, text = docs.stored_text
    assert name == "Deed intake 2026/0417 (1.0).txt" and "Price: EUR 412.000,00" in text
    assert docs.stored_provenance == {"playbook": "playbook/be-notary/deed-intake", "version": "1.0", "run": rid}  # where it came from
    assert docs.docs[r.json()["result_document_id"]] == (Scope.case(uuid.UUID(cid)), "playbook")
    assert c.put(f"/v1/cases/{cid}/playbooks/runs/{rid}/facts", json=confirm, headers=alice).status_code == 409
    # the access log has both steps
    actions = [e["action"] for e in c.get(f"/v1/cases/{cid}/events", headers=alice).json()]
    assert "playbook_started" in actions and "playbook_confirmed" in actions
    # a document the run read is deleted: the run stays, marked out of date; a closed case starts nothing
    assert c.delete(f"/v1/documents/{DOC}?case={cid}", headers=alice).status_code == 204
    assert c.get(f"/v1/cases/{cid}/playbooks/runs/{rid}", headers=alice).json()["out_of_date"] is True
    c.post(f"/v1/cases/{cid}/close", headers=alice)
    assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).status_code == 403


@needs_db
def test_an_admin_switches_a_playbook_off_and_it_leaves_every_case(office):
    c, kc, _, docs, _ = office
    alice, admin = as_user(kc, ALICE), admin_headers(kc)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    # the admin's list: every installed playbook, active unless switched off
    assert c.get("/v1/admin/playbooks", headers=alice).status_code == 403
    listed = c.get("/v1/admin/playbooks", headers=admin).json()
    assert [(p["id"], p["active"], p["case_types"]) for p in listed] == [("playbook/be-notary/deed-intake", True, ["sale"])]
    assert c.put("/v1/admin/playbooks/deed-intake", json={"active": False}, headers=alice).status_code == 403
    assert c.put("/v1/admin/playbooks/nope", json={"active": False}, headers=admin).status_code == 404
    r = c.put("/v1/admin/playbooks/deed-intake", json={"active": False}, headers=admin)
    assert r.status_code == 200 and r.json()["active"] is False
    # off: it isn't offered in the case and can't be started
    assert c.get(f"/v1/cases/{cid}/playbooks", headers=alice).json() == []
    assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).status_code == 404
    # on again
    assert c.put("/v1/admin/playbooks/deed-intake", json={"active": True}, headers=admin).json()["active"] is True
    assert [p["id"] for p in c.get(f"/v1/cases/{cid}/playbooks", headers=alice).json()] == ["playbook/be-notary/deed-intake"]


@needs_db
def test_a_run_fails_by_kind_when_the_answer_isnt_the_table(runs):
    kc, cases, docs = FakeKeycloak(), FakeCases(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([], text="Ik weet het niet."))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=FakeConversations(), cases=cases,
                     runs=runs, case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    with TestClient(app) as c:
        alice = as_user(kc, ALICE)
        cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
        assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).status_code == 404  # nothing to read
        docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
        rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"document_ids": [DOC]}, headers=alice).json()["id"]
        run = wait_for(c, f"/v1/cases/{cid}/playbooks/runs/{rid}", alice, "failed")
        assert run["error"] == "unreadable_answer" and run["facts"] == []
        assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"document_ids": [str(uuid.uuid4())]}, headers=alice).status_code == 404


@needs_db
def test_an_unreadable_answer_is_asked_for_once_more_with_a_stricter_reminder(runs):
    """Review 2026-10-17: the second attempt carries the reminder; a readable second answer makes the run."""
    kc, cases, docs = FakeKeycloak(), FakeCases(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    captured: list = []
    plain = llm_transport(captured, text="Ik weet het niet.")
    good = llm_transport(captured, text=TABLE)
    transport = httpx.MockTransport(lambda r: (good if "could not be read" in r.content.decode() else plain).handler(r))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=transport)
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=FakeConversations(), cases=cases,
                     runs=runs, case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    with TestClient(app) as c:
        alice = as_user(kc, ALICE)
        cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
        docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
        rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).json()["id"]
        run = wait_for(c, f"/v1/cases/{cid}/playbooks/runs/{rid}", alice, "checkpoint")
        assert len(captured) == 2 and "could not be read" in captured[1]["messages"][-1]["content"]
        assert captured[1]["max_tokens"] == 4096 and len(run["facts"]) == 13


@needs_db
def test_a_run_reading_when_the_gateway_stopped_is_failed_at_the_next_start(runs):
    """Review 2026-10-17: a restart used to leave a run spinning forever."""
    cid = uuid.uuid4()
    run = runs.create(cid, DEED_INTAKE, [DOC], ALICE, None)
    assert runs.interrupt(30 * 60) == 0  # the sweep: not stale yet
    assert runs.interrupt(0) == 1        # start-up: every reading run is dead
    got = runs.get(uuid.UUID(run.id), cid)
    assert got.status == "failed" and got.error == "interrupted" and got.finished_at is not None
    assert runs.interrupt(0) == 0
    runs.delete_case(cid)


@needs_db
def test_starting_runs_shares_the_chat_rate_limit(runs):
    from suveryn_api_gateway.ratelimit import RateLimits
    kc, cases, docs = FakeKeycloak(), FakeCases(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([], text=TABLE))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=FakeConversations(), cases=cases,
                     runs=runs, case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory(),
                     rate_limits=RateLimits(chat=2))
    with TestClient(app) as c:
        alice = as_user(kc, ALICE)
        cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
        docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
        codes = [c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).status_code for _ in range(3)]
        assert codes == [202, 202, 429]


@needs_db
def test_store_deletes_runs_with_the_case(runs):
    cid = uuid.uuid4()
    run = runs.create(cid, DEED_INTAKE, [DOC], ALICE, None)
    assert runs.get(uuid.UUID(run.id), cid).status == "reading" and runs.get(uuid.UUID(run.id), uuid.uuid4()) is None
    assert runs.confirm(uuid.UUID(run.id), cid, {}, "alice") is None  # not at the checkpoint
    assert runs.delete_case(cid) == 1 and runs.list(cid) == []


@needs_db
def test_only_so_many_runs_read_at_once(runs, monkeypatch):
    """The audit of 25 October 2026, finding 3: nothing bounded how many runs read at the same time.
    Two of one person's and four in all; one more is refused with a sentence until one finishes."""
    import asyncio
    import threading

    from suveryn_api_gateway.routes import playbooks as route

    monkeypatch.setattr(route, "MAX_RUNS_PER_USER", 2)
    monkeypatch.setattr(route, "MAX_RUNS", 3)
    release = threading.Event()
    plain = llm_transport([], text=TABLE).handler

    async def slow(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            while not release.is_set():  # the model is busy until the test says
                await asyncio.sleep(0.02)
        return plain(request)

    kc, cases, docs = FakeKeycloak(), FakeCases(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=httpx.MockTransport(slow))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=FakeConversations(), cases=cases,
                     runs=runs, case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    try:
        with TestClient(app) as c:
            alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
            cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
            c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
            docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
            start = lambda who: c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=who)  # noqa: E731
            assert [start(alice).status_code for _ in range(3)] == [202, 202, 429]  # two of hers at once
            r = start(bob)
            assert r.status_code == 202  # someone else's first: three in all
            r = start(bob)
            assert r.status_code == 429 and "too many playbook runs" in r.json()["detail"]  # the appliance's three
            release.set()
            first = c.get(f"/v1/cases/{cid}/playbooks/runs", headers=alice).json()[0]
            wait_for(c, f"/v1/cases/{cid}/playbooks/runs/{first['id']}", alice, "checkpoint")
            for _ in range(50):  # every place given back once the readings end
                if not route.slots_of(app).taken:
                    break
                time.sleep(0.05)
            assert not route.slots_of(app).taken
            assert start(alice).status_code == 202
    finally:
        release.set()
