"""Playbook runs (suveryn-tracker#51): deed intake as a routine (docs/design/playbooks.md, "The
routine"): the playbook asks for the agreement, reads the case's documents, asks about what it
couldn't find, waits at the checkpoint for a person, stores the summary as a document with origin
``playbook``; and it can be paused, stopped and cancelled. Reading the model's table is the
harness's and tested there (packages/harness/tests/test_facts.py); the order of steps without a
database is test_playbook_runtime.py."""

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
              status="done", documents=[DOC], started_by=ALICE, started_at="2026-10-17T10:00:00Z", facts=facts)
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
    s._execute("DELETE FROM turns WHERE run_id IN (SELECT id FROM playbook_runs WHERE started_by IN (%s, %s, %s, %s))", (ALICE, BOB, "notaris.test", "bob.test"))
    s._execute("DELETE FROM case_facts WHERE run_id IN (SELECT id FROM playbook_runs WHERE started_by IN (%s, %s, %s, %s))", (ALICE, BOB, "notaris.test", "bob.test"))
    s._execute("DELETE FROM playbook_runs WHERE started_by IN (%s, %s, %s, %s)", (ALICE, BOB, "notaris.test", "bob.test"))
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


RUNS = "/v1/cases/{cid}/playbooks/runs"
RUN = RUNS + "/{rid}"


def as_bob(kc) -> dict:
    """Bob with his own username: the run shows names, but rights are checked by id."""
    return {"Authorization": f"Bearer {kc.tokens(over={'sub': BOB, 'preferred_username': 'bob.test', 'name': 'Bob Test'})['access_token']}"}


def a_case_with_a_contributor(c, kc, role="reader"):
    alice, bob = as_user(kc, ALICE), as_bob(kc)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": role}, headers=alice)
    return cid, alice, bob


@needs_db
def test_deed_intake_asks_reads_asks_waits_for_a_person_and_stores_the_summary(office):
    c, kc, _, docs, captured = office
    cid, alice, bob = a_case_with_a_contributor(c, kc)
    docs.docs[str(uuid.uuid4())] = (Scope.case(uuid.UUID(cid)), "playbook")  # an earlier result: never read
    # which playbooks fit: a sale gets deed intake 1.1, covered, with its routine and its words in every language
    fits = c.get(f"/v1/cases/{cid}/playbooks", headers=bob).json()
    assert [(p["id"], p["covered"], p["version"]) for p in fits] == [("playbook/be-notary/deed-intake", True, "1.1")]
    assert [s["kind"] for s in fits[0]["steps"]] == ["request", "read", "ask", "checkpoint", "produce"]
    assert set(fits[0]["text"]) == {"en", "nl", "fr"} and fits[0]["text"]["en"]["labels"]["price"] == "Price"
    assert "{label}" in fits[0]["text"]["nl"]["questions"]["missing"]
    # a reader can't start; a contributor can, in Dutch; the case has no documents, so the playbook asks for them
    assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=bob).status_code == 403
    assert c.post(f"/v1/cases/{cid}/playbooks/estate-intake/runs", json={}, headers=alice).status_code == 404
    r = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"language": "nl"}, headers=alice)
    assert r.status_code == 202
    run = r.json()
    rid = run["id"]
    assert (run["status"], run["step"], run["language"], run["playbook_version"]) == ("waiting", "agreement", "nl", "1.1")
    assert run["steps"]["agreement"]["status"] == "active" and run["steps"]["read"]["status"] == "pending"
    assert [(t["role"], t["step_id"], t["by"]) for t in run["turns"]] == [("playbook", "agreement", "playbook/be-notary/deed-intake")]
    assert run["turns"][0]["text"].startswith("Laad de ondertekende verkoopovereenkomst op")
    # one live run per playbook per case
    r = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice)
    assert r.status_code == 409 and r.json()["detail"]["run"] == rid
    # the chip: the live run per readable case
    chip = c.get("/v1/playbooks/runs/active", headers=bob).json()[cid]
    assert chip["step"] == "agreement" and chip["step_kind"] == "request" and chip["title"]["nl"] == "Akte-intake"
    # answering is a contributor's; saying there is no agreement isn't allowed here; with the document in, the read starts
    assert c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "agreement"}, headers=bob).status_code == 403
    assert c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "agreement", "none": True}, headers=alice).status_code == 422
    assert c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "read"}, headers=alice).status_code == 409
    r = c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "agreement"}, headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "waiting" and r.json()["step"] == "agreement"  # still no document
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    r = c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "agreement", "text": "Het compromis staat erin."}, headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "reading" and r.json()["step"] == "read" and r.json()["documents"] == [DOC]
    assert "| sellers | | |" in captured[-1]["messages"][-1]["content"]  # the playbook's instructions went to the model
    # the model answered; the cadastral data wasn't in the documents, so the playbook asks for it, in Dutch, and waits
    run = wait_for(c, RUN.format(cid=cid, rid=rid), bob, "waiting")
    assert run["step"] == "missing" and run["steps"]["read"]["status"] == "done" and run["model"] == "Qwen3.8-27B-UD-Q4_K_M.gguf"
    by = {f["id"]: f for f in run["facts"]}
    assert by["price"]["value"] == "EUR 412.500,00" and by["price"]["citations"][0]["filename"] == "akte.pdf" and by["price"]["source"] == "document"
    assert by["cadastral"]["found"] is False and by["cadastral"]["source"] == "none" and by["cadastral"]["confirmed"] is None
    asked = [t for t in run["turns"] if t["step_id"] == "missing"]
    not_found = [f["id"] for f in run["facts"] if not f["found"]]
    assert [t["meta"]["fact"] for t in asked] == not_found and not_found[0] == "cadastral" and "Kadastrale gegevens" in asked[0]["text"]
    assert [t["role"] for t in run["turns"]] == ["playbook", "user", "user"] + ["playbook"] * len(not_found)
    # the answer: a proposed fact from a person; a fact not asked is refused
    assert c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "missing", "facts": {"price": "1"}}, headers=alice).status_code == 422
    r = c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "missing", "facts": {"cadastral": "Gent 5e afd., sectie B, nr. 123"}}, headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "waiting" and r.json()["step"] == "confirm"
    by = {f["id"]: f for f in r.json()["facts"]}
    assert by["cadastral"]["value"].startswith("Gent") and by["cadastral"]["source"] == "person" and by["cadastral"]["found"] is False
    assert by["cadastral"]["confirmed"] is None  # a person answered; nobody confirmed yet
    assert r.json()["turns"][-1]["role"] == "user" and "Gent" in r.json()["turns"][-1]["text"]
    # the checkpoint: a reader can't confirm; the contributor corrects the price and confirms the rest
    confirm = {"facts": [{"id": "price", "confirmed": "EUR 412.000,00"}]}
    assert c.put(RUN.format(cid=cid, rid=rid) + "/facts", json=confirm, headers=bob).status_code == 403
    assert c.put(RUN.format(cid=cid, rid=rid) + "/facts", json={"facts": [{"id": "x", "confirmed": ""}]}, headers=alice).status_code == 422
    r = c.put(RUN.format(cid=cid, rid=rid) + "/facts", json=confirm, headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "done" and r.json()["step"] is None and r.json()["confirmed_by"] == "notaris.test"
    by = {f["id"]: f for f in r.json()["facts"]}
    assert by["price"]["confirmed"] == "EUR 412.000,00" and by["price"]["value"] == "EUR 412.500,00"
    assert by["sellers"]["confirmed"] == "Jan Peeters en Marie Claes" and by["cadastral"]["confirmed"].startswith("Gent")
    assert r.json()["steps"]["summary"]["status"] == "done" and r.json()["finished_at"]
    # the summary is a document in the case with origin playbook, named after the playbook, the case and the run's version,
    # in the run's language; its text is what 1.0 wrote for the same confirmed facts
    name, text = docs.stored_text
    assert name == "Deed intake 2026/0417 (1.1).txt" and text.startswith("Akte-intake 2026/0417\n\nplaybook/be-notary/deed-intake 1.1")
    assert "Prijs: EUR 412.000,00 (akte.pdf p. 2)" in text and "Kadastrale gegevens: Gent 5e afd., sectie B, nr. 123" in text
    assert docs.stored_provenance == {"playbook": "playbook/be-notary/deed-intake", "version": "1.1", "run": rid}
    assert docs.docs[r.json()["result_document_id"]] == (Scope.case(uuid.UUID(cid)), "playbook")
    assert c.put(RUN.format(cid=cid, rid=rid) + "/facts", json=confirm, headers=alice).status_code == 409
    assert cid not in c.get("/v1/playbooks/runs/active", headers=alice).json()  # done: no chip
    # the facts' record: one row per version, the model's reading superseded by the person's, never rewritten
    store = c.app.state.runs.get()
    rows = store.fact_rows(uuid.UUID(rid))
    price = [(r_["status"], r_["source"]["kind"], r_["by"]) for r_ in rows if r_["fact_id"] == "price"]
    assert price == [("superseded", "document", "playbook/be-notary/deed-intake"), ("confirmed", "person", "notaris.test")]
    cadastral = [(r_["status"], r_["source"]["kind"]) for r_ in rows if r_["fact_id"] == "cadastral"]
    assert cadastral == [("superseded", "none"), ("superseded", "person"), ("confirmed", "person")]
    title = [(r_["status"], r_["source"]["kind"]) for r_ in rows if r_["fact_id"] == "title"]
    assert title == [("superseded", "none"), ("not_established", "person")]  # asked, left empty, cleared at the checkpoint
    # the access log has every step
    actions = [e["action"] for e in c.get(f"/v1/cases/{cid}/events", headers=alice).json()]
    assert {"playbook_started", "playbook_answered", "playbook_confirmed"} <= set(actions)
    # a document the run read is deleted: the run stays, marked out of date; a closed case starts nothing
    assert c.delete(f"/v1/documents/{DOC}?case={cid}", headers=alice).status_code == 204
    assert c.get(RUN.format(cid=cid, rid=rid), headers=alice).json()["out_of_date"] is True
    c.post(f"/v1/cases/{cid}/close", headers=alice)
    assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).status_code == 403


@needs_db
def test_a_run_is_paused_and_resumed_by_anyone_who_contributes(office):
    c, kc, _, docs, _ = office
    cid, alice, bob = a_case_with_a_contributor(c, kc, "contributor")
    rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).json()["id"]
    r = c.post(RUN.format(cid=cid, rid=rid) + "/pause", headers=bob)
    assert r.status_code == 200 and r.json()["status"] == "paused" and r.json()["paused_by"] == "bob.test" and r.json()["paused_at"]
    assert c.post(RUN.format(cid=cid, rid=rid) + "/pause", headers=bob).status_code == 409
    assert c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "agreement"}, headers=alice).status_code == 409  # paused: nothing advances
    assert c.get("/v1/playbooks/runs/active", headers=alice).json()[cid]["status"] == "paused"  # still shown
    r = c.post(RUN.format(cid=cid, rid=rid) + "/resume", headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "waiting" and r.json()["step"] == "agreement" and r.json()["paused_by"] is None
    actions = [e["action"] for e in c.get(f"/v1/cases/{cid}/events", headers=alice).json()]
    assert "playbook_paused" in actions and "playbook_resumed" in actions


@needs_db
def test_stop_keeps_confirmed_facts_and_drops_proposed_ones(office):
    c, kc, _, docs, _ = office
    cid, alice, bob = a_case_with_a_contributor(c, kc, "contributor")
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).json()["id"]
    c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "agreement"}, headers=alice)
    run = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "waiting")
    assert run["step"] == "missing"
    # a contributor who didn't start it and doesn't manage the case can't end it; the starter can
    assert c.post(RUN.format(cid=cid, rid=rid) + "/stop", headers=bob).status_code == 403
    r = c.post(RUN.format(cid=cid, rid=rid) + "/stop", headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "stopped" and r.json()["ended_by"] == "notaris.test"
    store = c.app.state.runs.get()
    statuses = {r_["status"] for r_ in store.fact_rows(uuid.UUID(rid)) if r_["source"]["kind"] == "document"}
    assert statuses == {"superseded"}  # proposed and gone; nothing was confirmed
    assert c.post(RUN.format(cid=cid, rid=rid) + "/stop", headers=alice).status_code == 409
    assert c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "missing", "facts": {}}, headers=alice).status_code == 409
    # terminal: a new run can start
    assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).status_code == 202


@needs_db
def test_cancel_reverts_confirmed_facts_and_withdraws_the_product(office):
    c, kc, cases, docs, _ = office
    cid, alice, bob = a_case_with_a_contributor(c, kc, "contributor")
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=bob).json()["id"]  # bob starts it
    c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "agreement"}, headers=bob)
    wait_for(c, RUN.format(cid=cid, rid=rid), bob, "waiting")
    c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "missing", "facts": {"cadastral": "Gent"}}, headers=bob)
    r = c.put(RUN.format(cid=cid, rid=rid) + "/facts", json={"facts": [{"id": "price", "confirmed": "EUR 1"}]}, headers=bob)
    assert r.status_code == 200 and r.json()["status"] == "done"
    doc = r.json()["result_document_id"]
    # done is terminal too: it can't be cancelled through the run... except by design it can, by the starter or the manager
    # (a result that should not have happened); alice manages the case
    r = c.post(RUN.format(cid=cid, rid=rid) + "/cancel", json={"reason": "wrong file"}, headers=alice)
    assert r.status_code == 409  # a finished run is not cancelled: its facts are the case's now (stop/cancel act on live runs)
    # a live run, then: start again, confirm nothing yet, cancel at the checkpoint after answering
    rid2 = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=bob).json()["id"]
    c.post(RUN.format(cid=cid, rid=rid2) + "/answer", json={"step_id": "agreement"}, headers=bob)
    wait_for(c, RUN.format(cid=cid, rid=rid2), bob, "waiting")
    c.post(RUN.format(cid=cid, rid=rid2) + "/answer", json={"step_id": "missing", "facts": {"cadastral": "Gent"}}, headers=bob)
    r = c.post(RUN.format(cid=cid, rid=rid2) + "/cancel", json={"reason": "wrong file"}, headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["ended_reason"] == "wrong file"
    assert r.json()["ended_by"] == "notaris.test"
    actions = [e["action"] for e in c.get(f"/v1/cases/{cid}/events", headers=alice).json()]
    assert "playbook_cancelled" in actions
    assert doc not in getattr(docs, "withdrawn", {})  # the first run's product stands


@needs_db
def test_cancel_supersedes_everything_the_run_established_and_keeps_the_record(runs):
    """Pod check of d0f680e, question Q: a cancelled run leaves nothing of its own as the case's, read
    or confirmed; the rows stay, superseded, so the history is whole (through the store: a routine with
    steps after its checkpoint can be live with confirmed facts)."""
    cid = uuid.uuid4()
    run = runs.create(cid, DEED_INTAKE, [DOC], ALICE, None)
    rid = uuid.UUID(run.id)
    runs.write_facts(cid, rid, "read", [dict(fact_id="price", kind="amount", value="1", status="proposed",
                                              source={"kind": "document", "citations": []}, by=DEED_INTAKE.id),
                                         dict(fact_id="deposit", kind="amount", value="2", status="proposed",
                                              source={"kind": "document", "citations": []}, by=DEED_INTAKE.id)])
    first = runs.current_versions(rid)["price"]["id"]
    runs.write_facts(cid, rid, "confirm", [dict(fact_id="price", kind="amount", value="2", status="confirmed",
                                                 source={"kind": "person", "checkpoint": True}, by="alice", replaces=first)])
    assert [f.confirmed for f in runs.facts_for_run(rid)] == ["2", None]
    assert runs.end(rid, "cancelled", "alice", "oops") and runs.discard_all(rid) == 2  # the confirmed price and the proposed deposit
    facts = runs.facts_for_run(rid)
    assert facts[0].confirmed is None and facts[0].value == "1"  # no longer the case's; what was read is still shown
    rows = [(r["fact_id"], r["status"]) for r in runs.fact_rows(rid)]
    assert rows == [("price", "superseded"), ("deposit", "superseded"), ("price", "superseded")]  # kept, nothing rewritten
    runs.delete_case(cid)


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
        assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"document_ids": [str(uuid.uuid4())]}, headers=alice).status_code == 404
        docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
        rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"document_ids": [DOC]}, headers=alice).json()["id"]
        c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "agreement"}, headers=alice)
        run = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "failed")
        assert run["error"] == "unreadable_answer" and run["facts"] == [] and run["step"] == "read"


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
        c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "agreement"}, headers=alice)
        run = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "waiting")
        assert len(captured) == 2 and "could not be read" in captured[1]["messages"][-1]["content"]
        assert captured[1]["max_tokens"] == 4096 and len(run["facts"]) == 13


@needs_db
def test_a_run_reading_when_the_gateway_stopped_is_failed_at_the_next_start(runs):
    """Review 2026-10-17: a restart used to leave a run spinning forever."""
    cid = uuid.uuid4()
    run = runs.create(cid, DEED_INTAKE, [DOC], ALICE, None)
    runs.set_step(uuid.UUID(run.id), "read", "reading", {"read": __import__("suveryn_api_gateway.playbooks", fromlist=["StepState"]).StepState(status="active")})
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
        codes = []
        for i in range(3):  # one run per case: a case has one live run of a playbook
            cid = c.post("/v1/cases", json={**NEW, "reference": f"2026/{i}"}, headers=alice).json()["id"]
            codes.append(c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).status_code)
        assert codes == [202, 202, 429]


@needs_db
def test_store_deletes_runs_with_the_case(runs):
    cid = uuid.uuid4()
    run = runs.create(cid, DEED_INTAKE, [DOC], ALICE, None)
    rid = uuid.UUID(run.id)
    assert runs.get(rid, cid).status == "waiting" and runs.get(rid, uuid.uuid4()) is None
    runs.append(rid, "playbook", DEED_INTAKE.id, "Upload the agreement.", "agreement")
    runs.write_facts(cid, rid, "read", [dict(fact_id="price", kind="amount", value="1", status="proposed", source={"kind": "none"}, by="x")])
    assert runs.count_for_run(rid) == 1 and len(runs.fact_rows(rid)) == 1
    assert runs.delete_case(cid) == 1 and runs.list(cid) == []
    assert runs.count_for_run(rid) == 0 and runs.fact_rows(rid) == []  # the thread and the facts went with the case


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
            n = iter(range(100))

            def start(who):  # a case per run (one live run of a playbook per case); its document is in, so the start reads at once
                cid = c.post("/v1/cases", json={**NEW, "reference": f"2026/{next(n)}"}, headers=alice).json()["id"]
                c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
                docs.docs[str(uuid.uuid4())] = (Scope.case(uuid.UUID(cid)), "uploaded")
                return c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=who), cid

            codes = [start(alice)[0].status_code for _ in range(3)]
            assert codes == [202, 202, 429]  # two of hers at once
            r, cid = start(bob)
            assert r.status_code == 202  # someone else's first: three in all
            rid = r.json()["id"]
            r, busy_cid = start(bob)
            assert r.status_code == 429 and "too many playbook runs" in r.json()["detail"]  # the appliance's three
            busy = c.get(RUNS.format(cid=busy_cid), headers=alice).json()[0]
            assert busy["status"] == "failed" and busy["error"] == "busy"  # the refused run is a record too; start it again later
            release.set()
            wait_for(c, RUN.format(cid=cid, rid=rid), alice, "waiting")
            for _ in range(50):  # every place given back once the readings end
                if not route.slots_of(app).taken:
                    break
                time.sleep(0.05)
            assert not route.slots_of(app).taken
            assert start(alice)[0].status_code == 202
    finally:
        release.set()
